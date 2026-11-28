import ExpoModulesCore
import WebKit

// A book's pages. The web view asks the app for every file a page needs (zim://<book>/<path>) and JavaScript reads it
// from the book. Nothing else loads: books carry their websites' scripts, and none of them may reach the internet.
final class BookView: ExpoView, WKNavigationDelegate, WKUIDelegate {
  let onAsk = EventDispatcher()
  let onPage = EventDispatcher()
  let onLeave = EventDispatcher()
  let onOpen = EventDispatcher()

  let files = BookFiles()
  private var web: WKWebView!
  private var watching: [NSKeyValueObservation] = []
  private var ready = false  // WebKit's rules that block everything but the book are in place
  private var queued: URL?

  // Schemes a page may load from: its book, and what a page makes for itself
  static let inside: Set<String> = [BookFiles.scheme, "about", "data", "blob"]

  // Block every load, then let those through. WebKit's rules have no "or".
  static let rules = "[" + (["{\"trigger\":{\"url-filter\":\".*\"},\"action\":{\"type\":\"block\"}}"]
    + inside.map { "{\"trigger\":{\"url-filter\":\"^\($0):\"},\"action\":{\"type\":\"ignore-previous-rules\"}}" })
    .joined(separator: ",") + "]"

  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    let config = WKWebViewConfiguration()
    config.setURLSchemeHandler(files, forURLScheme: BookFiles.scheme)
    config.websiteDataStore = .nonPersistent()
    config.allowsInlineMediaPlayback = true
    config.dataDetectorTypes = []
    config.preferences.javaScriptCanOpenWindowsAutomatically = false
    web = WKWebView(frame: bounds, configuration: config)
    web.navigationDelegate = self
    web.uiDelegate = self
    web.allowsLinkPreview = false
    web.isFindInteractionEnabled = true
    addSubview(web)
    files.view = self
    watching = [
      web.observe(\.title) { [weak self] _, _ in self?.page() },
      web.observe(\.url) { [weak self] _, _ in self?.page() },
      web.observe(\.canGoBack) { [weak self] _, _ in self?.page() },
      web.observe(\.canGoForward) { [weak self] _, _ in self?.page() },
      web.observe(\.isLoading) { [weak self] _, _ in self?.page() },
    ]
    WKContentRuleListStore.default().compileContentRuleList(
      forIdentifier: "tinfoilkit-books-only", encodedContentRuleList: BookView.rules
    ) { [weak self] list, _ in
      DispatchQueue.main.async {
        guard let self else { return }
        // Should the rules ever fail to build, pages still carry a Content-Security-Policy that keeps them in
        if let list { self.web.configuration.userContentController.add(list) }
        self.ready = true
        if let url = self.queued {
          self.queued = nil
          self.web.load(URLRequest(url: url))
        }
      }
    }
  }

  override func layoutSubviews() {
    super.layoutSubviews()
    web.frame = bounds
  }

  func start(_ address: String) {
    guard web.url == nil, queued == nil, let url = URL(string: address) else { return }
    load(url)
  }

  func load(_ url: URL) {
    if ready {
      web.load(URLRequest(url: url))
    } else {
      queued = url
    }
  }

  func back() { web.goBack() }
  func forward() { web.goForward() }
  func find() { web.findInteraction?.presentFindNavigator(showingReplace: false) }

  private func page() {
    onPage([
      "url": web.url?.absoluteString ?? "",
      "title": web.title ?? "",
      "back": web.canGoBack,
      "forward": web.canGoForward,
      "loading": web.isLoading,
    ])
  }

  // The book's own pages load. A link out of it is the app's to offer; anything else going out is stopped.
  func webView(
    _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    if let scheme = action.request.url?.scheme?.lowercased(), BookView.inside.contains(scheme) {
      return decisionHandler(.allow)
    }
    decisionHandler(.cancel)
    if action.navigationType == .linkActivated, let url = action.request.url {
      onLeave(["url": url.absoluteString])
    }
  }

  // A file the web view can't show (an e-book, a document) goes to the app, which opens it in another app
  func webView(
    _ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
    decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
  ) {
    if response.isForMainFrame, !response.canShowMIMEType, let url = response.response.url {
      decisionHandler(.cancel)
      onOpen(["url": url.absoluteString, "mime": response.response.mimeType ?? ""])
    } else {
      decisionHandler(.allow)
    }
  }

  // A link that would open a new window opens here
  func webView(
    _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
    for action: WKNavigationAction, windowFeatures: WKWindowFeatures
  ) -> WKWebView? {
    if action.request.url?.scheme?.lowercased() == BookFiles.scheme {
      webView.load(action.request)
    }
    return nil
  }

  // iOS ends a page's process when memory runs low: show the page again
  func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
    webView.reload()
  }
}

// Hands each file a page asks for to JavaScript, which reads it from the book, then gives the page what comes back:
// the bytes, or where they lie in the book's file (pictures, PDFs, videos), read from there a piece at a time.
final class BookFiles: NSObject, WKURLSchemeHandler {
  static let scheme = "zim"
  static let policy = "default-src zim: data: blob: 'unsafe-inline' 'unsafe-eval'"

  weak var view: BookView?
  private var tasks: [Int: WKURLSchemeTask] = [:]  // all of this runs on the main thread
  private var count = 0

  func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
    count += 1
    tasks[count] = task
    let url = task.request.url
    view?.onAsk([
      "id": count,
      "url": url?.absoluteString ?? "",
      "main": url != nil && task.request.mainDocumentURL == url,
    ])
  }

  func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {
    tasks = tasks.filter { $0.value !== task }
  }

  func respond(_ id: Int, status: Int, mime: String, body: Data) {
    guard let task = tasks.removeValue(forKey: id), let url = task.request.url else { return }
    task.didReceive(BookFiles.response(url, status, mime, body.count))
    task.didReceive(body)
    task.didFinish()
  }

  func respondFile(_ id: Int, status: Int, mime: String, path: String, offset: UInt64, length: Int) {
    guard let task = tasks[id], let url = task.request.url else { return }
    var start = offset
    var count = length
    var code = status
    var headers = ["Accept-Ranges": "bytes"]
    if let part = BookFiles.range(task.request.value(forHTTPHeaderField: "Range"), length) {
      let (from, to) = part
      start += UInt64(from)
      count = to - from + 1
      code = 206
      headers["Content-Range"] = "bytes \(from)-\(to)/\(length)"
    }
    let file: FileHandle
    do {
      file = try FileHandle(forReadingFrom: URL(fileURLWithPath: path))
      try file.seek(toOffset: start)
    } catch {
      tasks[id] = nil
      task.didFailWithError(error)
      return
    }
    task.didReceive(BookFiles.response(url, code, mime, count, headers))
    // A quarter of a megabyte at a time, letting the app get on with other things in between
    func next(_ left: Int) {
      guard tasks[id] != nil else {
        try? file.close()
        return
      }
      let piece = left > 0 ? autoreleasepool { (try? file.read(upToCount: min(left, 1 << 18))) ?? Data() } : Data()
      if piece.isEmpty {
        try? file.close()
        tasks[id] = nil
        if left > 0 {
          task.didFailWithError(CocoaError(.fileReadCorruptFile))
        } else {
          task.didFinish()
        }
        return
      }
      task.didReceive(piece)
      DispatchQueue.main.async { next(left - piece.count) }
    }
    next(count)
  }

  static func response(_ url: URL, _ status: Int, _ mime: String, _ length: Int, _ extra: [String: String] = [:])
    -> URLResponse
  {
    var headers = extra
    headers["Content-Type"] = mime
    headers["Content-Length"] = String(length)
    headers["Content-Security-Policy"] = policy
    return HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)
      ?? URLResponse(url: url, mimeType: mime, expectedContentLength: length, textEncodingName: nil)
  }

  // The part of a file a video or audio player asks for: "bytes=a-b", "bytes=a-" or "bytes=-n"
  static func range(_ header: String?, _ length: Int) -> (Int, Int)? {
    guard let header, header.hasPrefix("bytes="), length > 0 else { return nil }
    let spec = header.dropFirst(6).prefix { $0 != "," }
    let parts = spec.split(separator: "-", omittingEmptySubsequences: false)
    guard parts.count == 2 else { return nil }
    let from = Int(parts[0].trimmingCharacters(in: .whitespaces))
    let to = Int(parts[1].trimmingCharacters(in: .whitespaces))
    switch (from, to) {
    case let (from?, to?) where from <= to && from < length: return (from, min(to, length - 1))
    case let (from?, nil) where from < length: return (from, length - 1)
    case let (nil, last?) where last > 0: return (max(0, length - last), length - 1)
    default: return nil
    }
  }
}
