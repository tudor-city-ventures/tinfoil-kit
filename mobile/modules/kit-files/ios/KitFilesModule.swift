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
  }
}
