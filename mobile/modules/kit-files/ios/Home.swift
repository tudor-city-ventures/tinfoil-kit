import Foundation
import Network

// A kit found on this Wi-Fi: its computer's name, and where its gate answers
struct FoundKit: Sendable {
  let name: String
  let host: String
  let port: Int
}

// The kits shared on this Wi-Fi. Each says it's there by Bonjour, as _tinfoilkit._tcp under its computer's name (the
// kit's gate.go), which app.json lists for iOS. The first search asks once to find devices on the local network.
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
    let browser = NWBrowser(for: .bonjour(type: "_tinfoilkit._tcp", domain: "local."), using: .tcp)
    browser.browseResultsChangedHandler = { [self] results, _ in
      for result in results {
        if case let .service(name, _, _, _) = result.endpoint { resolve(name, result.endpoint) }
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
  private func resolve(_ name: String, _ endpoint: NWEndpoint) {
    guard found[name] == nil, done != nil else { return }
    let params = NWParameters.tcp
    if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options { ip.version = .v4 }
    let connection = NWConnection(to: endpoint, using: params)
    connection.stateUpdateHandler = { [self] state in
      switch state {
      case .ready:
        if case let .hostPort(host, port)? = connection.currentPath?.remoteEndpoint, case let .ipv4(address) = host {
          let dotted = address.rawValue.map { String($0) }.joined(separator: ".")  // without the network's name
          found[name] = FoundKit(name: name, host: dotted, port: Int(port.rawValue))
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
