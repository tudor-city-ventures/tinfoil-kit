import ExpoModulesCore
#if canImport(FoundationModels)
import FoundationModels
#endif

public class KitFilesModule: Module {
  private let downloads = Downloads()

  public func definition() -> ModuleDefinition {
    Name("KitFiles")

    // A file, or part of one, into a file, while the app is open: see Downloads.swift
    AsyncFunction("download") { (o: DownloadOptions, promise: Promise) in
      self.downloads.start(o, promise: promise)
    }

    Function("stopDownloads") {
      self.downloads.stop()
    }

    // Books stay out of iCloud and computer backups (Apple's rule for downloads that can be downloaded again).
    // On a folder, it covers everything in it.
    Function("excludeFromBackup") { (path: String) in
      var url = URL(fileURLWithPath: path)
      var values = URLResourceValues()
      values.isExcludedFromBackup = true
      try url.setResourceValues(values)
    }

    // Books download with the app closed, and are checked and filed in the library as they land: see Books.swift
    OnCreate {
      Books.shared.reconnect()
    }

    OnAppBecomesActive {
      Books.shared.reconnect()
    }

    Function("libraryPath") { () -> String in
      let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      let library = documents.appendingPathComponent("library", isDirectory: true)
      try? FileManager.default.createDirectory(at: library, withIntermediateDirectories: true)
      return library.path
    }

    AsyncFunction("startBook") { (o: BookOptions) in
      try Books.shared.start(o)
    }

    Function("stopBook") { (id: String) in
      Books.shared.stop(id)
    }

    Function("forgetBook") { (id: String) in
      Books.shared.forget(id)
    }

    AsyncFunction("books") { (promise: Promise) in
      Books.shared.list(promise)
    }

    // The AI built into the phone (Apple Intelligence, from iOS 26): whether it can answer now ("off" until the person
    // turns it on in Settings, "downloading" while its model comes), and its answer
    Function("aiState") { () -> String in
      #if canImport(FoundationModels)
      if #available(iOS 26.0, *) {
        switch SystemLanguageModel.default.availability {
        case .available: return "ready"
        case .unavailable(.appleIntelligenceNotEnabled): return "off"
        case .unavailable(.modelNotReady): return "downloading"
        default: return "none"
        }
      }
      #endif
      return "none"
    }

    AsyncFunction("aiAnswer") { (instructions: String, prompt: String) async throws -> String in
      #if canImport(FoundationModels)
      if #available(iOS 26.0, *) {
        let session = LanguageModelSession(instructions: instructions)
        return try await session.respond(to: prompt).content
      }
      #endif
      throw Exception(name: "NoAI", description: "This phone has no AI built in")
    }

    View(BookView.self) {
      Events("onAsk", "onPage", "onLeave", "onOpen")

      Prop("start") { (view: BookView, address: String) in
        view.start(address)
      }

      AsyncFunction("load") { (view: BookView, address: String) in
        if let url = URL(string: address) { view.load(url) }
      }.runOnQueue(.main)

      AsyncFunction("back") { (view: BookView) in
        view.back()
      }.runOnQueue(.main)

      AsyncFunction("forward") { (view: BookView) in
        view.forward()
      }.runOnQueue(.main)

      AsyncFunction("find") { (view: BookView) in
        view.find()
      }.runOnQueue(.main)

      AsyncFunction("respond") { (view: BookView, id: Int, status: Int, mime: String, body: Data) in
        view.files.respond(id, status: status, mime: mime, body: body)
      }.runOnQueue(.main)

      AsyncFunction("respondFile") {
        (view: BookView, id: Int, status: Int, mime: String, path: String, offset: Double, length: Double) in
        view.files.respondFile(id, status: status, mime: mime, path: path, offset: UInt64(offset), length: Int(length))
      }.runOnQueue(.main)
    }
  }
}
