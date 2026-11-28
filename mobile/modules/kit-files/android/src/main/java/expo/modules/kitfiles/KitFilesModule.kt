package expo.modules.kitfiles

import expo.modules.kotlin.Promise
import expo.modules.kotlin.functions.Coroutine
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.security.SecureRandom
import kotlin.concurrent.thread

class KitFilesModule : Module() {
  private val downloads = Downloads { appContext.reactContext }
  private val ai = AI { appContext.reactContext }

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

    // A book from a file, such as one sent with Quick Share: see Adding in Books.kt
    AsyncFunction("addBook") { from: String, to: String, promise: Promise ->
      val context = appContext.reactContext ?: throw IllegalStateException("The app isn't running")
      thread(name = "adding") {
        try {
          promise.resolve(Adding.add(context, from, File(to)).toDouble())
        } catch (e: Failure) {
          promise.reject(e)
        } catch (e: Exception) { // such as a file Android no longer lets the app read
          promise.reject(Failure("ERR_FILE", e.message ?: e.toString()))
        }
      }
    }

    Function("adding") {
      mapOf("done" to Adding.done.toDouble(), "total" to Adding.total.toDouble())
    }

    Function("moveBook") { from: String, to: String ->
      Adding.move(from, to)
    }

    // A cluster of a book's pages, decompressed: see Clusters in Books.kt
    Function("unzstd") { path: String, offset: Double, length: Double ->
      Clusters.unzstd(path, offset, length)
    }

    // The kits shared on this Wi-Fi, and phones shared like one: see Home.kt
    AsyncFunction("findKits") { seconds: Double, promise: Promise ->
      val context = appContext.reactContext ?: return@AsyncFunction promise.resolve(emptyList<Any>())
      KitFinder(context).find(seconds) { promise.resolve(it) }
    }

    // This phone shared like a kit at home, for another phone to copy from: see Home.kt
    AsyncFunction("startSharing") { o: ShareOptions ->
      Sharing.start(appContext.reactContext ?: throw IllegalStateException("The app isn't running"), o)
    }

    Function("stopSharing") {
      Sharing.stop()
    }

    Function("sharing") {
      Sharing.state(appContext.reactContext ?: throw IllegalStateException("The app isn't running"))
    }

    // The code another phone types: 8 digits from the system's secure random numbers
    Function("newCode") {
      val random = SecureRandom()
      (1..8).joinToString("") { random.nextInt(10).toString() }
    }

    // The AI built into the phone, where there is one: see AI.kt
    AsyncFunction("aiState") Coroutine { ->
      ai.state()
    }

    AsyncFunction("aiDownload") Coroutine { cellular: Boolean ->
      ai.download(cellular)
    }

    AsyncFunction("aiAnswer") Coroutine { instructions: String, prompt: String ->
      ai.answer(instructions, prompt)
    }

    OnDestroy {
      ai.close()
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
