import ExpoModulesCore
import Foundation

struct DownloadOptions: Record {
  @Field var url: String = ""
  @Field var path: String = ""
  @Field var cellular: Bool = false
  @Field var headers: [String: String] = [:]  // a kit at home's access code
  @Field var offset: Double? = nil
  @Field var length: Double? = nil
  @Field var at: Double? = nil
}

// Downloads while the app is open, written into a file as they come: a whole file, or one part of one. A part is taken
// only as asked for: a server that ignored the range would be sending the whole file, which for the world map is
// 120 GB, so anything but exactly those bytes stops at once. Over Wi-Fi only, unless mobile data is allowed.
final class Downloads: NSObject, URLSessionDataDelegate {
  private final class Job {
    let file: FileHandle
    let range: (from: Int64, to: Int64)?
    let promise: Promise
    var received: Int64 = 0
    var failure: (code: String, message: String)?

    init(file: FileHandle, range: (from: Int64, to: Int64)?, promise: Promise) {
      self.file = file
      self.range = range
      self.promise = promise
    }
  }

  private let lock = NSLock()
  private var jobs: [Int: Job] = [:]
  private lazy var session: URLSession = {
    let config = URLSessionConfiguration.default
    config.timeoutIntervalForRequest = 30
    config.requestCachePolicy = .reloadIgnoringLocalCacheData
    config.urlCache = nil
    config.httpMaximumConnectionsPerHost = 6
    let queue = OperationQueue()
    queue.maxConcurrentOperationCount = 1
    return URLSession(configuration: config, delegate: self, delegateQueue: queue)
  }()

  func start(_ o: DownloadOptions, promise: Promise) {
    guard let url = URL(string: o.url) else {
      return promise.reject("ERR_URL", "Not a web address: \(o.url)")
    }
    var request = URLRequest(url: url)
    request.allowsCellularAccess = o.cellular
    request.allowsExpensiveNetworkAccess = o.cellular  // a phone's hotspot, too
    request.allowsConstrainedNetworkAccess = o.cellular  // Low Data Mode
    request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")  // the file's own bytes, never unzipped ones
    for (name, value) in o.headers { request.setValue(value, forHTTPHeaderField: name) }
    var range: (from: Int64, to: Int64)?
    if let offset = o.offset, let length = o.length, length > 0 {
      range = (Int64(offset), Int64(offset) + Int64(length) - 1)
      request.setValue("bytes=\(range!.from)-\(range!.to)", forHTTPHeaderField: "Range")
    }
    let fileURL = URL(fileURLWithPath: o.path)
    let file: FileHandle
    do {
      if let at = o.at {
        // into a file that's there already: one deleted since (its plan stopped) stays deleted
        guard let f = try? FileHandle(forWritingTo: fileURL) else {
          return promise.reject("ERR_GONE", "The file it was going into is gone")
        }
        try f.seek(toOffset: UInt64(at))
        file = f
      } else {
        try FileManager.default.createDirectory(
          at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: o.path, contents: nil)
        file = try FileHandle(forWritingTo: fileURL)
      }
    } catch {
      return promise.reject("ERR_FILE", error.localizedDescription)
    }
    let task = session.dataTask(with: request)
    lock.lock()
    jobs[task.taskIdentifier] = Job(file: file, range: range, promise: promise)
    lock.unlock()
    task.resume()
  }

  func stop() {
    session.getAllTasks { tasks in tasks.forEach { $0.cancel() } }
  }

  private func job(_ task: URLSessionTask) -> Job? {
    lock.lock()
    defer { lock.unlock() }
    return jobs[task.taskIdentifier]
  }

  func urlSession(
    _ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
  ) {
    guard let job = job(dataTask), let http = response as? HTTPURLResponse else {
      return completionHandler(.cancel)
    }
    if let range = job.range {
      guard http.statusCode == 206 else {
        job.failure = (http.statusCode == 200 ? "ERR_NO_RANGE" : "ERR_HTTP_\(http.statusCode)", "The server said \(http.statusCode)")
        return completionHandler(.cancel)
      }
      // bytes from-to/size: from where asked, to where asked or the file's end before it
      let parts = (http.value(forHTTPHeaderField: "Content-Range") ?? "")
        .replacingOccurrences(of: "bytes ", with: "").split(whereSeparator: { $0 == "-" || $0 == "/" })
        .compactMap { Int64($0) }
      guard parts.count == 3, parts[0] == range.from, parts[1] == range.to || (parts[1] < range.to && parts[1] == parts[2] - 1)
      else {
        job.failure = ("ERR_NO_RANGE", "The server sent other bytes than those asked for")
        return completionHandler(.cancel)
      }
    } else if http.statusCode != 200 {
      job.failure = ("ERR_HTTP_\(http.statusCode)", "The server said \(http.statusCode)")
      return completionHandler(.cancel)
    }
    completionHandler(.allow)
  }

  func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
    guard let job = job(dataTask), job.failure == nil else { return }
    if let range = job.range, job.received + Int64(data.count) > range.to - range.from + 1 {
      job.failure = ("ERR_NO_RANGE", "The server sent more than was asked for")
      return dataTask.cancel()
    }
    do {
      try job.file.write(contentsOf: data)
      job.received += Int64(data.count)
    } catch {
      job.failure = ("ERR_FILE", error.localizedDescription)
      dataTask.cancel()
    }
  }

  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    lock.lock()
    let job = jobs.removeValue(forKey: task.taskIdentifier)
    lock.unlock()
    guard let job else { return }
    try? job.file.close()
    if let failure = job.failure {
      return job.promise.reject(failure.code, failure.message)
    }
    guard let error = error as? URLError else {
      if let error { return job.promise.reject("ERR_DOWNLOAD", error.localizedDescription) }
      return job.promise.resolve(Double(job.received))
    }
    switch error.code {
    case .cancelled:
      job.promise.reject("ERR_STOPPED", "Stopped")
    case _ where error.networkUnavailableReason != nil:
      job.promise.reject("ERR_NOT_ON_WIFI", "Waiting for Wi-Fi")  // only mobile data, a hotspot or Low Data Mode
    case .notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost,
      .dnsLookupFailed, .dataNotAllowed, .internationalRoamingOff, .secureConnectionFailed:
      job.promise.reject("ERR_OFFLINE", error.localizedDescription)
    default:
      job.promise.reject("ERR_DOWNLOAD", error.localizedDescription)
    }
  }
}
