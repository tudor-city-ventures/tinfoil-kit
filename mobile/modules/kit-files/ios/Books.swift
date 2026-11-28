import CryptoKit
import ExpoFileSystem
import ExpoModulesCore
import Foundation
import os

private let logger = Logger(subsystem: "com.tinfoilkit.app", category: "books")

struct BookOptions: Record {
  @Field var id: String = ""  // this download's own id
  @Field var book: String = ""
  @Field var title: String = ""  // Android shows it while it downloads
  @Field var url: String = ""
  @Field var incoming: String = ""  // where it lands to be checked
  @Field var path: String = ""  // where it goes once it's checked
  @Field var sha256: String? = nil
  @Field var cellular: Bool = false
  @Field var headers: [String: String] = [:]  // a kit at home's access code
}

// A book's download: carried in its task's description, so it outlives the app, and kept as a file from when it
// lands until the app has seen how it went.
private struct Book: Codable {
  var id: String
  var book: String
  var incoming: String
  var path: String
  var sha256: String?
  var cellular: Bool
  var state = "downloading"  // then downloaded (being checked), then ready or failed
  var error: String?
}

private struct Failure: Error {
  let message: String
}

private final class Flag: @unchecked Sendable {  // its lock makes it safe across threads
  private let lock = NSLock()
  private var value = false
  var isSet: Bool {
    lock.lock()
    defer { lock.unlock() }
    return value
  }
  func set() {
    lock.lock()
    value = true
    lock.unlock()
  }
}

// Books download with the app closed, by iOS's background transfers, and each is checked against its SHA-256 and
// filed in the library as soon as it lands: iOS wakes the app for it, though no JavaScript runs then. Two sessions:
// one that waits for Wi-Fi (never a phone's hotspot or Low Data Mode), and one that may use mobile data, for when the
// person allows it.
final class Books: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {  // its state is behind its lock
  static let shared = Books()
  private static let wifi = (Bundle.main.bundleIdentifier ?? "com.tinfoilkit.app") + ".books"
  private static let anyNetwork = wifi + ".cellular"

  private let lock = NSLock()
  private var sessions: [String: URLSession] = [:]
  private var wakeups: [String: () -> Void] = [:]
  private var checking: Set<String> = []
  private let checks = DispatchQueue(label: "com.tinfoilkit.books.check")  // one book at a time
  private let pending = DispatchGroup()
  private let records: URL

  override private init() {
    let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    records = support.appendingPathComponent("books", isDirectory: true)
    try? FileManager.default.createDirectory(at: records, withIntermediateDirectories: true)
    super.init()
  }

  static func owns(_ identifier: String) -> Bool {
    identifier == wifi || identifier == anyNetwork
  }

  // iOS woke the app for one of these sessions' downloads
  func wake(_ identifier: String, completion: @escaping () -> Void) {
    lock.lock()
    wakeups[identifier] = completion
    lock.unlock()
    _ = connect(identifier)
  }

  // The app opened: iOS hands over what happened while it was closed, and books whose check was cut short get it
  func reconnect() {
    _ = connect(Self.wifi)
    _ = connect(Self.anyNetwork)
    for book in saved() where book.state == "downloaded" {
      check(book)
    }
  }

  func start(_ o: BookOptions) throws {
    guard let url = URL(string: o.url) else { throw Failure(message: "Not a web address: \(o.url)") }
    let book = Book(id: o.id, book: o.book, incoming: o.incoming, path: o.path, sha256: o.sha256, cellular: o.cellular)
    let session = connect(o.cellular ? Self.anyNetwork : Self.wifi)
    let task: URLSessionDownloadTask
    if let data = takeResumeData(book) {
      task = session.downloadTask(withResumeData: data)  // carries on from where the last try failed
    } else {
      var request = URLRequest(url: url)
      request.allowsCellularAccess = o.cellular
      request.allowsExpensiveNetworkAccess = o.cellular
      request.allowsConstrainedNetworkAccess = o.cellular
      for (name, value) in o.headers { request.setValue(value, forHTTPHeaderField: name) }
      task = session.downloadTask(with: request)
    }
    task.taskDescription = String(decoding: try JSONEncoder().encode(book), as: UTF8.self)
    task.resume()
    logger.notice("Book \(book.id, privacy: .public): started, mobile data \(o.cellular ? "allowed" : "not allowed", privacy: .public)")
  }

  func stop(_ id: String) {
    forget(id)
    for session in [connect(Self.wifi), connect(Self.anyNetwork)] {
      session.getAllTasks { tasks in
        for task in tasks {
          guard let book = Self.book(task), book.id == id else { continue }
          task.cancel()
          try? FileManager.default.removeItem(at: self.resumeFile(book))
        }
      }
    }
  }

  private static func message(_ status: Int) -> String {
    switch status {
    case 401: return "The kit's access code has changed"
    case 404, 410: return "The file isn't there any more"
    default: return "The server said \(status)"
    }
  }

  func forget(_ id: String) {
    try? FileManager.default.removeItem(at: record(id))
  }

  // Every book download this knows of: the ones still downloading, and the ones that landed since the app last looked
  func list(_ promise: Promise) {
    var out: [[String: Any]] = saved().map { book in
      ["id": book.id, "book": book.book, "state": book.state, "error": book.error ?? "", "cellular": book.cellular]
    }
    let group = DispatchGroup()
    let lock = NSLock()
    for session in [connect(Self.wifi), connect(Self.anyNetwork)] {
      group.enter()
      session.getAllTasks { tasks in
        lock.lock()
        for task in tasks where task.state == .running || task.state == .suspended {
          guard let book = Self.book(task) else { continue }
          out.append([
            "id": book.id, "book": book.book, "state": "downloading", "cellular": book.cellular,
            "received": Double(task.countOfBytesReceived), "total": Double(max(task.countOfBytesExpectedToReceive, 0)),
          ])
        }
        lock.unlock()
        group.leave()
      }
    }
    group.notify(queue: .global()) { promise.resolve(out) }
  }

  // A file's SHA-256, a few megabytes at a time: each read is let go before the next, so a book of many gigabytes
  // never piles up in memory. Nil when stopped first.
  static func sha256(_ path: String, stop: () -> Bool = { false }) throws -> String? {
    let handle = try FileHandle(forReadingFrom: URL(fileURLWithPath: path))
    defer { try? handle.close() }
    var hash = SHA256()
    while true {
      if stop() { return nil }
      guard let chunk = try autoreleasepool(invoking: { try handle.read(upToCount: 4 << 20) }), !chunk.isEmpty else {
        break
      }
      hash.update(data: chunk)
    }
    return hash.finalize().map { String(format: "%02x", $0) }.joined()
  }

  // MARK: - Downloads

  func urlSession(
    _ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL
  ) {
    guard var book = Self.book(downloadTask) else { return }
    let status = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
    do {
      guard status == 200 || status == 206 else {
        throw Failure(message: Self.message(status))
      }
      // the file is iOS's only until this returns
      let incoming = URL(fileURLWithPath: book.incoming)
      try FileManager.default.createDirectory(
        at: incoming.deletingLastPathComponent(), withIntermediateDirectories: true)
      try? FileManager.default.removeItem(at: incoming)
      try FileManager.default.moveItem(at: location, to: incoming)
      book.state = "downloaded"
      save(book)
      logger.notice("Book \(book.id, privacy: .public): landed")
      check(book)
    } catch {
      book.state = "failed"
      book.error = Self.message(error)
      save(book)
      logger.error("Book \(book.id, privacy: .public): \(book.error ?? "", privacy: .public)")
    }
  }

  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    guard let error = error as NSError?, var book = Self.book(task) else { return }
    let resume = error.userInfo[NSURLSessionDownloadTaskResumeData] as? Data
    if error.domain == NSURLErrorDomain && error.code == NSURLErrorCancelled {
      // Stopped by the app: nothing more to do. Stopped by iOS (the app was swiped away, Background App Refresh is
      // off, or the phone needed the room): carry on from where it got to.
      guard error.userInfo[NSURLErrorBackgroundTaskCancelledReasonKey] != nil else { return }
      let next = resume.map { session.downloadTask(withResumeData: $0) }
        ?? task.originalRequest.map { session.downloadTask(with: $0) }
      next?.taskDescription = task.taskDescription
      next?.resume()
      logger.notice("Book \(book.id, privacy: .public): iOS stopped it, so it carries on \(resume == nil ? "from the start" : "where it was", privacy: .public)")
      return
    }
    if let resume {
      try? resume.write(to: resumeFile(book), options: .atomic)  // so Try again carries on from here
    }
    book.state = "failed"
    book.error = Self.message(error)
    save(book)
    logger.error("Book \(book.id, privacy: .public): \(book.error ?? "", privacy: .public)")
  }

  func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
    guard let identifier = session.configuration.identifier else { return }
    // iOS may suspend the app as soon as it's told, so only once the books that came in are checked, or put off
    pending.notify(queue: .main) {
      self.lock.lock()
      let completion = self.wakeups.removeValue(forKey: identifier)
      self.lock.unlock()
      completion?()
      // Expo's file system holds on to every session's wakeup, not only its own, until told its events are done
      ExpoAppDelegateSubscriberRepository.getSubscriberOfType(FileSystemBackgroundSessionHandler.self)?
        .invokeCompletionHandler(forSessionIdentifier: identifier)
    }
  }

  // MARK: - Checking

  private func check(_ book: Book) {
    lock.lock()
    let fresh = checking.insert(book.id).inserted
    lock.unlock()
    guard fresh else { return }
    pending.enter()
    checks.async {
      defer {
        self.lock.lock()
        self.checking.remove(book.id)
        self.lock.unlock()
        self.pending.leave()
      }
      // With the app in the background iOS gives it a little while, which a book of a few gigabytes fits in. A
      // bigger one is checked when the app is next woken or opened.
      let done = DispatchSemaphore(value: 0)
      let started = Flag()
      let stop = Flag()
      ProcessInfo.processInfo.performExpiringActivity(withReason: "Checking a downloaded book") { expired in
        if expired {
          stop.set()
          if !started.isSet { done.signal() }
          return
        }
        started.set()
        self.finish(book, stop: stop)
        done.signal()
      }
      done.wait()
    }
  }

  private func finish(_ book: Book, stop: Flag) {
    var book = book
    let incoming = URL(fileURLWithPath: book.incoming)
    do {
      guard FileManager.default.fileExists(atPath: book.incoming) else {
        throw Failure(message: "The download went missing")
      }
      if let want = book.sha256 {
        guard let got = try Self.sha256(book.incoming, stop: { stop.isSet }) else { return }
        guard got == want.lowercased() else { throw Failure(message: "It came through damaged") }
      }
      guard FileManager.default.fileExists(atPath: record(book.id).path) else {
        try? FileManager.default.removeItem(at: incoming)  // the app let it go while it was checked
        return
      }
      let path = URL(fileURLWithPath: book.path)
      try? FileManager.default.removeItem(at: path)
      try FileManager.default.moveItem(at: incoming, to: path)
      book.state = "ready"
    } catch {
      try? FileManager.default.removeItem(at: incoming)
      book.state = "failed"
      book.error = Self.message(error)
    }
    if FileManager.default.fileExists(atPath: record(book.id).path) { save(book) }
    logger.notice("Book \(book.id, privacy: .public): \(book.state, privacy: .public) \(book.error ?? "", privacy: .public)")
  }

  // MARK: - Records

  private func connect(_ identifier: String) -> URLSession {
    lock.lock()
    defer { lock.unlock() }
    if let session = sessions[identifier] { return session }
    let cellular = identifier == Self.anyNetwork
    let config = URLSessionConfiguration.background(withIdentifier: identifier)
    config.sessionSendsLaunchEvents = true
    config.isDiscretionary = false
    config.allowsCellularAccess = cellular
    config.allowsExpensiveNetworkAccess = cellular  // a phone's hotspot
    config.allowsConstrainedNetworkAccess = cellular  // Low Data Mode
    let queue = OperationQueue()
    queue.maxConcurrentOperationCount = 1
    let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
    sessions[identifier] = session
    return session
  }

  private static func book(_ task: URLSessionTask) -> Book? {
    guard let text = task.taskDescription else { return nil }
    return try? JSONDecoder().decode(Book.self, from: Data(text.utf8))
  }

  private static func message(_ error: Error) -> String {
    if let failure = error as? Failure { return failure.message }
    let error = error as NSError
    if error.domain == NSURLErrorDomain && error.code == NSURLErrorCannotWriteToFile
      || error.domain == NSCocoaErrorDomain && error.code == NSFileWriteOutOfSpaceError
    {
      return "Not enough free space"
    }
    return error.localizedDescription
  }

  private func record(_ id: String) -> URL {
    records.appendingPathComponent(id.replacingOccurrences(of: "/", with: "_") + ".json")
  }

  private func save(_ book: Book) {
    guard let data = try? JSONEncoder().encode(book) else { return }
    try? data.write(to: record(book.id), options: .atomic)
  }

  private func saved() -> [Book] {
    let files = (try? FileManager.default.contentsOfDirectory(at: records, includingPropertiesForKeys: nil)) ?? []
    return files.filter { $0.pathExtension == "json" }.compactMap { file in
      (try? Data(contentsOf: file)).flatMap { try? JSONDecoder().decode(Book.self, from: $0) }
    }
  }

  private func resumeFile(_ book: Book) -> URL {
    let name = URL(fileURLWithPath: book.incoming).lastPathComponent
    return records.appendingPathComponent(name + (book.cellular ? ".cellular" : "") + ".resume")
  }

  private func takeResumeData(_ book: Book) -> Data? {
    let file = resumeFile(book)
    defer { try? FileManager.default.removeItem(at: file) }
    return try? Data(contentsOf: file)
  }
}

// iOS relaunches the app in the background when a book lands, and hands it the session's events through here
public class KitFilesAppDelegate: ExpoAppDelegateSubscriber {
  public func application(
    _ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
    completionHandler: @escaping () -> Void
  ) {
    guard Books.owns(identifier) else { return completionHandler() }
    Books.shared.wake(identifier, completion: completionHandler)
  }
}
