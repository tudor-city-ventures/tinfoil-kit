import ExpoModulesCore
import Foundation
import Network

// A kit found on this Wi-Fi, or a phone shared like one: its name, and where it answers
struct FoundKit: Sendable {
  let name: String
  let host: String
  let port: Int
  let phone: Bool
}

// The kits shared on this Wi-Fi. Each says it's there by Bonjour, as _tinfoilkit._tcp under its computer's name (the
// kit's gate.go), which app.json lists for iOS; a phone shared like one says kind=phone. The first search asks once to
// find devices on the local network.
final class KitFinder: @unchecked Sendable {  // its state is touched on its queue only
  private let queue = DispatchQueue(label: "com.tinfoilkit.kits")
  private var browser: NWBrowser?
  private var connections: [NWConnection] = []
  private var found: [String: FoundKit] = [:]
  private var done: CheckedContinuation<[FoundKit], Never>?

  // What it finds in that many seconds
  static func find(seconds: Double) async -> [FoundKit] {
    let finder = KitFinder()
    return await withCheckedContinuation { done in
      finder.queue.async { finder.start(done, seconds: seconds) }
    }
  }

  private func start(_ done: CheckedContinuation<[FoundKit], Never>, seconds: Double) {
    self.done = done
    let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_tinfoilkit._tcp", domain: "local."), using: .tcp)
    browser.browseResultsChangedHandler = { [self] results, _ in
      for result in results {
        guard case let .service(name, _, _, _) = result.endpoint else { continue }
        var phone = false
        if case let .bonjour(txt) = result.metadata { phone = txt["kind"] == "phone" }
        resolve(name, phone, result.endpoint)
      }
    }
    browser.stateUpdateHandler = { [self] state in
      if case .failed = state { finish() }  // as when the person doesn't allow the local network
    }
    self.browser = browser
    browser.start(queue: queue)
    queue.asyncAfter(deadline: .now() + seconds) { [self] in finish() }
  }

  // Its address, by connecting: the kit answers on IPv4 only
  private func resolve(_ name: String, _ phone: Bool, _ endpoint: NWEndpoint) {
    guard found[name] == nil, done != nil else { return }
    let params = NWParameters.tcp
    if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options { ip.version = .v4 }
    let connection = NWConnection(to: endpoint, using: params)
    connection.stateUpdateHandler = { [self] state in
      switch state {
      case .ready:
        if case let .hostPort(host, port)? = connection.currentPath?.remoteEndpoint, case let .ipv4(address) = host {
          let dotted = address.rawValue.map { String($0) }.joined(separator: ".")  // without the network's name
          found[name] = FoundKit(name: name, host: dotted, port: Int(port.rawValue), phone: phone)
        }
        connection.cancel()
      case .failed, .waiting:
        connection.cancel()
      default:
        break
      }
    }
    connections.append(connection)
    connection.start(queue: queue)
  }

  private func finish() {
    guard let done else { return }
    self.done = nil
    browser?.cancel()
    connections.forEach { $0.cancel() }
    done.resume(returning: found.values.sorted { $0.name < $1.name })
  }
}

struct ShareOptions: Record {
  @Field var name: String = ""
  @Field var code: String = ""
  @Field var listing: String = ""  // what /data/files answers: the books and the map, as a kit lists them
  @Field var files: [String: String] = [:]  // each file's path in the listing, and the file on this phone
  @Field var folders: [String: String] = [:]  // a folder's path in it (the map's fonts and icons), and this phone's
}

// This phone shared like a kit at home, for another phone on the Wi-Fi to copy its books and map: it says it's there
// by Bonjour as a kit does, with kind=phone, and answers as a kit's gate does, only with the code. A small HTTP/1.1
// server: GET and HEAD, one range at a time, one request a connection, and nothing but the listing and the files it
// names. On IPv4, never over mobile data. iOS stops it once the app is in the background, so the share screen keeps
// the phone awake, and starts it again when the app is back.
final class Sharing: @unchecked Sendable {  // its state is touched on its queue only
  static let shared = Sharing()
  private static let kitPort: UInt16 = 8000  // a kit's, so a typed address needs none
  private static let tries = 10  // wrong codes, then it stops: as many as a kit allows from one address in 10 minutes
  private static let most = 16  // connections at once
  private static let chunk = 256 << 10
  private static let allowed = CharacterSet(
    charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._@,+-")
  private static let dates: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = TimeZone(identifier: "GMT")
    f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss 'GMT'"
    return f
  }()

  private let queue = DispatchQueue(label: "com.tinfoilkit.sharing")
  private var listener: NWListener?
  private var starting: Promise?
  private var options = ShareOptions()
  private var open: [ObjectIdentifier: NWConnection] = [:]
  private var waiting = Set<ObjectIdentifier>()  // connections that haven't asked for anything yet
  private var port: UInt16 = 0
  private var wrong = 0
  private var sent: Int64 = 0
  private var stopped = ""  // why it stopped by itself: "tries" (too many wrong codes) or "failed"

  // Resolves with the port it listens on: a kit's, or any other if something else has that one
  func start(_ o: ShareOptions, promise: Promise) {
    queue.async { [self] in
      halt()
      options = o
      wrong = 0
      sent = 0
      stopped = ""
      listen(Self.kitPort, promise)
    }
  }

  func stop() {
    queue.async { [self] in halt() }
  }

  func state() -> [String: Any] {
    let addresses = Self.addresses()
    return queue.sync { () -> [String: Any] in
      [
        "on": listener != nil, "port": Int(port), "addresses": addresses, "sent": Double(sent),
        "copying": open.count - waiting.count, "stopped": stopped,
      ]
    }
  }

  private func listen(_ port: UInt16, _ promise: Promise) {
    let params = NWParameters.tcp
    params.allowLocalEndpointReuse = true  // started again at once, on the same port
    params.prohibitedInterfaceTypes = [.cellular]
    if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options { ip.version = .v4 }
    let listener: NWListener
    do {
      listener = try NWListener(using: params, on: NWEndpoint.Port(rawValue: port) ?? .any)
    } catch {
      return promise.reject("ERR_SHARE", error.localizedDescription)
    }
    listener.service = NWListener.Service(
      name: options.name, type: "_tinfoilkit._tcp", domain: nil, txtRecord: NWTXTRecord(["v": "1", "kind": "phone"]))
    listener.stateUpdateHandler = { [self, weak listener] state in
      guard let listener, listener === self.listener else { return }
      switch state {
      case .ready:
        self.port = listener.port?.rawValue ?? port
        starting?.resolve(Int(self.port))
        starting = nil
      case .failed(let error):
        let first = starting
        starting = nil
        halt()
        guard let first else {
          stopped = "failed"
          return
        }
        if port != 0, case .posix(.EADDRINUSE) = error { return listen(0, first) }
        first.reject("ERR_SHARE", error.localizedDescription)
      default:
        break
      }
    }
    listener.newConnectionHandler = { [self] connection in accept(connection) }
    starting = promise
    self.listener = listener
    listener.start(queue: queue)
  }

  private func halt() {
    listener?.cancel()
    listener = nil
    open.values.forEach { $0.cancel() }
    open = [:]
    waiting = []
    starting?.reject("ERR_STOPPED", "Sharing stopped")
    starting = nil
  }

  private func accept(_ c: NWConnection) {
    guard open.count < Self.most else { return c.cancel() }
    let id = ObjectIdentifier(c)
    open[id] = c
    waiting.insert(id)
    c.stateUpdateHandler = { [self] state in
      switch state {
      case .ready:
        if c.currentPath?.usesInterfaceType(.cellular) == true { c.cancel() }
      case .failed, .cancelled:
        open[id] = nil
        waiting.remove(id)
      default:
        break
      }
    }
    c.start(queue: queue)
    receive(c, Data())
    // one that asks for nothing goes, so it can't keep others out
    queue.asyncAfter(deadline: .now() + 10) { [self] in
      if waiting.contains(id) { c.cancel() }
    }
  }

  // The request's head, up to the blank line
  private func receive(_ c: NWConnection, _ head: Data) {
    c.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [self] data, _, done, error in
      var head = head
      if let data { head.append(data) }
      if let end = head.range(of: Data("\r\n\r\n".utf8)) {
        waiting.remove(ObjectIdentifier(c))
        answer(c, String(decoding: head[..<end.lowerBound], as: UTF8.self))
      } else if error != nil || done || head.count > 8192 {
        c.cancel()
      } else {
        receive(c, head)
      }
    }
  }

  private func answer(_ c: NWConnection, _ head: String) {
    let lines = head.components(separatedBy: "\r\n")
    let request = lines[0].split(separator: " ")
    var fields: [String: String] = [:]
    for line in lines.dropFirst() {
      guard let colon = line.firstIndex(of: ":") else { continue }
      fields[line[..<colon].lowercased()] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
    }
    guard request.count == 3, request[0] == "GET" || request[0] == "HEAD" else {
      return reply(c, 405, #"{"error": "only GET and HEAD"}"#)
    }
    let bare = request[0] == "HEAD"
    let auth = fields["authorization"] ?? ""
    var given = ""
    if auth.lowercased().hasPrefix("bearer ") {
      given = String(auth.dropFirst(7)).filter { $0.isLetter || $0.isNumber }
    }
    guard !given.isEmpty, Self.same(given, options.code) else {
      if !given.isEmpty {
        wrong += 1
        if wrong >= Self.tries, listener != nil {
          stopped = "tries"  // no more tries: the person starts again, with a new code
          listener?.cancel()
          listener = nil
        }
      }
      return reply(c, 401, #"{"error": "this needs the phone's code"}"#, bare: bare)
    }
    var path = String(request[1])
    if let query = path.firstIndex(of: "?") { path = String(path[..<query]) }
    let top = "/data/files"
    if path == top { return reply(c, 200, options.listing, bare: bare) }
    guard path.hasPrefix(top + "/"), let file = local(String(path.dropFirst(top.count + 1))) else {
      return reply(c, 404, #"{"error": "not shared"}"#, bare: bare)
    }
    serve(c, file, fields, bare)
  }

  // The file on this phone that a path in the listing names: one of its files, or one in a folder it names
  private func local(_ encoded: String) -> String? {
    guard let path = encoded.removingPercentEncoding else { return nil }
    if let file = options.files[path] { return file }
    for (folder, dir) in options.folders where path.hasPrefix(folder + "/") {
      let rest = String(path.dropFirst(folder.count + 1))
      let plain = rest.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { part in
        !part.isEmpty && !part.hasPrefix(".") && part.unicodeScalars.allSatisfy { Self.allowed.contains($0) }
      }
      return plain ? "\(dir)/\(rest)" : nil
    }
    return nil
  }

  private func serve(_ c: NWConnection, _ path: String, _ fields: [String: String], _ bare: Bool) {
    guard let info = try? FileManager.default.attributesOfItem(atPath: path),
      (info[.type] as? FileAttributeType) == .typeRegular,
      let size = (info[.size] as? NSNumber)?.int64Value,
      let file = FileHandle(forReadingAtPath: path)
    else { return reply(c, 404, #"{"error": "not on this phone"}"#, bare: bare) }
    let modified = (info[.modificationDate] as? Date) ?? Date(timeIntervalSince1970: 0)
    let tag = "\"\(size)-\(Int64(modified.timeIntervalSince1970))\""
    let date = Self.dates.string(from: modified)
    var from: Int64 = 0
    var to = size - 1
    var status = 200
    // a range, unless it's of another version of the file than this
    if let range = fields["range"], fields["if-range"].map({ $0 == tag || $0 == date }) ?? true {
      guard let r = Self.range(range, size) else {
        try? file.close()
        return reply(c, 416, "", bare: bare, extra: ["Content-Range": "bytes */\(size)"])
      }
      (from, to, status) = (r.from, r.to, 206)
    }
    var extra = ["Accept-Ranges": "bytes", "ETag": tag, "Last-Modified": date]
    if status == 206 { extra["Content-Range"] = "bytes \(from)-\(to)/\(size)" }
    guard (try? file.seek(toOffset: UInt64(from))) != nil else {
      try? file.close()
      return c.cancel()
    }
    let length = to - from + 1
    c.send(
      content: Self.head(status, "application/octet-stream", length, extra),
      completion: .contentProcessed { [self] error in
        guard error == nil, !bare else {
          try? file.close()
          return error == nil ? finish(c) : c.cancel()
        }
        stream(c, file, length)
      })
  }

  private func stream(_ c: NWConnection, _ file: FileHandle, _ left: Int64) {
    guard left > 0 else {
      try? file.close()
      return finish(c)
    }
    guard let bytes = try? file.read(upToCount: Int(min(left, Int64(Self.chunk)))), !bytes.isEmpty else {
      try? file.close()
      return c.cancel()  // shorter than it was: the other phone sees its copy end early
    }
    c.send(
      content: bytes,
      completion: .contentProcessed { [self] error in
        guard error == nil else {
          try? file.close()
          return c.cancel()
        }
        sent += Int64(bytes.count)
        stream(c, file, left - Int64(bytes.count))
      })
  }

  private func reply(
    _ c: NWConnection, _ status: Int, _ body: String, bare: Bool = false, extra: [String: String] = [:]
  ) {
    let bytes = Data(body.utf8)
    var data = Self.head(status, "application/json", Int64(bytes.count), extra)
    if !bare { data.append(bytes) }
    c.send(content: data, completion: .contentProcessed { [self] _ in finish(c) })
  }

  private func finish(_ c: NWConnection) {
    c.send(
      content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { _ in c.cancel() })
  }

  private static func head(_ status: Int, _ type: String, _ length: Int64, _ extra: [String: String]) -> Data {
    let reasons = [
      200: "OK", 206: "Partial Content", 401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
      416: "Range Not Satisfiable",
    ]
    var s = "HTTP/1.1 \(status) \(reasons[status] ?? "")\r\nContent-Type: \(type)\r\nContent-Length: \(length)\r\n"
    for (name, value) in extra { s += "\(name): \(value)\r\n" }
    s += "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
    return Data(s.utf8)
  }

  // A Range header's one range in a file of that size, or nil when it asks for none this answers
  private static func range(_ header: String, _ size: Int64) -> (from: Int64, to: Int64)? {
    guard header.hasPrefix("bytes="), !header.contains(",") else { return nil }
    let ends = header.dropFirst(6).split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
      .map { $0.trimmingCharacters(in: .whitespaces) }
    guard ends.count == 2 else { return nil }
    if ends[0].isEmpty {  // the last n bytes
      guard let n = Int64(ends[1]), n > 0, size > 0 else { return nil }
      return (max(0, size - n), size - 1)
    }
    guard let from = Int64(ends[0]), from >= 0, from < size else { return nil }
    guard !ends[1].isEmpty else { return (from, size - 1) }
    guard let to = Int64(ends[1]), to >= from else { return nil }
    return (from, min(to, size - 1))
  }

  // The same code, in the same time whatever it starts with
  private static func same(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8)
    let y = Array(b.utf8)
    guard x.count == y.count else { return false }
    return zip(x, y).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
  }

  // This phone's addresses on the Wi-Fi, or on its own hotspot
  private static func addresses() -> [String] {
    var list: [String] = []
    var first: UnsafeMutablePointer<ifaddrs>?
    guard getifaddrs(&first) == 0 else { return [] }
    defer { freeifaddrs(first) }
    var at = first
    while let a = at?.pointee {
      at = a.ifa_next
      let name = String(cString: a.ifa_name)
      guard let address = a.ifa_addr, address.pointee.sa_family == UInt8(AF_INET),
        a.ifa_flags & UInt32(IFF_UP) != 0, name.hasPrefix("en") || name.hasPrefix("bridge")
      else { continue }
      var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
      let length = socklen_t(address.pointee.sa_len)
      if getnameinfo(address, length, &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
        list.append(host.withUnsafeBufferPointer { String(cString: $0.baseAddress!) })
      }
    }
    return list
  }
}
