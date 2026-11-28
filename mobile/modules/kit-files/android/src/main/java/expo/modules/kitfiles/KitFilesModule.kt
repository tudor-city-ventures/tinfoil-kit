package expo.modules.kitfiles

import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class KitFilesModule : Module() {
  private val downloads = Downloads { appContext.reactContext }

  private fun books() = Books.get(appContext.reactContext ?: throw IllegalStateException("The app isn't running"))

  override fun definition() = ModuleDefinition {
    Name("KitFiles")

    // A file, or part of one, into a file, while the app is open: see Downloads.kt
    AsyncFunction("download") { o: DownloadOptions, promise: Promise ->
      downloads.start(o, promise)
    }

    Function("stopDownloads") {
      downloads.stop()
    }

    // Books download with the app closed, and are checked and filed in the library as they land: see Books.kt
    // Made here: outside the app's private folders, Expo's file system writes only where something already is
    Function("libraryPath") {
      books().library.apply { mkdirs() }.path
    }

    AsyncFunction("startBook") { o: BookOptions ->
      books().start(o)
    }

    Function("stopBook") { id: String ->
      books().stop(id)
    }

    Function("forgetBook") { id: String ->
      books().forget(id)
    }

    AsyncFunction("books") {
      books().list()
    }

    // The kits shared on this Wi-Fi: see Home.kt
    AsyncFunction("findKits") { seconds: Double, promise: Promise ->
      val context = appContext.reactContext ?: return@AsyncFunction promise.resolve(emptyList<Any>())
      KitFinder(context).find(seconds) { promise.resolve(it) }
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
