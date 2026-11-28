import CryptoKit
import ExpoModulesCore

public class KitFilesModule: Module {
  public func definition() -> ModuleDefinition {
    Name("KitFiles")

    // Books stay out of iCloud and computer backups (Apple's rule for downloads that can be downloaded again).
    // On a folder, it covers everything in it.
    Function("excludeFromBackup") { (path: String) in
      var url = URL(fileURLWithPath: path)
      var values = URLResourceValues()
      values.isExcludedFromBackup = true
      try url.setResourceValues(values)
    }

    // A file's SHA-256, a megabyte at a time: each read is let go before the next, so a book of many gigabytes
    // never piles up in memory.
    AsyncFunction("sha256") { (path: String) -> String in
      let handle = try FileHandle(forReadingFrom: URL(fileURLWithPath: path))
      defer { try? handle.close() }
      var hash = SHA256()
      while let chunk = try autoreleasepool(invoking: { try handle.read(upToCount: 1 << 20) }), !chunk.isEmpty {
        hash.update(data: chunk)
      }
      return hash.finalize().map { String(format: "%02x", $0) }.joined()
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
