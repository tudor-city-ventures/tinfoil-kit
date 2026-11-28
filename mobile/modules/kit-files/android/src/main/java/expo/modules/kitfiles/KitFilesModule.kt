package expo.modules.kitfiles

import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.security.MessageDigest

class KitFilesModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("KitFiles")

    // A file's SHA-256, a megabyte at a time
    AsyncFunction("sha256") { path: String ->
      val digest = MessageDigest.getInstance("SHA-256")
      File(path).inputStream().use { input ->
        val buffer = ByteArray(1 shl 20)
        while (true) {
          val n = input.read(buffer)
          if (n < 0) break
          digest.update(buffer, 0, n)
        }
      }
      digest.digest().joinToString("") { "%02x".format(it) }
    }

    // A view's functions run on the main thread
    View(BookView::class) {
      Events("onAsk", "onPage", "onLeave", "onOpen")

      Prop("start") { view: BookView, address: String ->
        view.start(address)
      }

      AsyncFunction("load") { view: BookView, address: String ->
        view.load(address)
      }

      AsyncFunction("back") { view: BookView ->
        view.back()
      }

      AsyncFunction("forward") { view: BookView ->
        view.forward()
      }

      // The web view's own threads wait for these
      AsyncFunction("respond") { view: BookView, id: Int, status: Int, mime: String, body: ByteArray ->
        view.respond(id, status, mime, body)
      }

      AsyncFunction("respondFile") { view: BookView, id: Int, status: Int, mime: String, path: String, offset: Double, length: Double ->
        view.respondFile(id, status, mime, path, offset.toLong(), length.toLong())
      }

      OnViewDestroys { view: BookView ->
        view.destroy()
      }
    }
  }
}
