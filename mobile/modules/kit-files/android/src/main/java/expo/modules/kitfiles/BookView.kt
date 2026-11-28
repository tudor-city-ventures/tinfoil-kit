package expo.modules.kitfiles

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.ViewGroup
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.viewevent.EventDispatcher
import expo.modules.kotlin.views.ExpoView
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.io.RandomAccessFile
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

// A book's pages. The web view asks the app for every file a page needs (https://<book>.zim.tinfoilkit.invalid/<path>:
// Android's web view stands in only for https) and JavaScript reads it from the book. Nothing else loads: books carry
// their websites' scripts, and none of them may reach the internet.
@SuppressLint("ViewConstructor", "SetJavaScriptEnabled")
class BookView(context: Context, appContext: AppContext) : ExpoView(context, appContext) {
  private val onAsk by EventDispatcher()
  private val onPage by EventDispatcher()
  private val onLeave by EventDispatcher()
  private val onOpen by EventDispatcher()

  private val main = Handler(Looper.getMainLooper())
  private val answers = ConcurrentHashMap<Int, CompletableFuture<WebResourceResponse>>()
  private val ranges = ConcurrentHashMap<Int, String>() // what part of a file a video or audio player asked for
  private val count = AtomicInteger()
  private var started = false

  val web: WebView = WebView(context).apply {
    layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
    settings.javaScriptEnabled = true
    settings.domStorageEnabled = true
    settings.allowFileAccess = false
    settings.allowContentAccess = false
    settings.setGeolocationEnabled(false)
    settings.setSupportMultipleWindows(false)
    settings.javaScriptCanOpenWindowsAutomatically = false
    settings.builtInZoomControls = true
    settings.displayZoomControls = false
    settings.textZoom = (resources.configuration.fontScale * 100).toInt() // the phone's text size
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      settings.safeBrowsingEnabled = false // it checks addresses with Google; a book's are all its own
    }
    webViewClient = Pages()
    webChromeClient = object : WebChromeClient() {
      override fun onReceivedTitle(view: WebView, title: String?) = page()
    }
    // A file the web view can't show (a PDF, an e-book) goes to the app, which opens it in another app
    setDownloadListener { url, _, _, mime, _ -> onOpen(mapOf("url" to url, "mime" to (mime ?: ""))) }
  }

  init {
    addView(web)
  }

  fun start(address: String) {
    if (started) return
    started = true
    web.loadUrl(address)
  }

  fun load(address: String) = web.loadUrl(address)

  fun back() {
    if (web.canGoBack()) web.goBack()
  }

  fun forward() {
    if (web.canGoForward()) web.goForward()
  }

  fun respond(id: Int, status: Int, mime: String, body: ByteArray) {
    answers[id]?.complete(response(status, mime, ByteArrayInputStream(body), body.size.toLong(), emptyMap()))
  }

  fun respondFile(id: Int, status: Int, mime: String, path: String, offset: Long, length: Long) {
    val answer = answers[id] ?: return
    var start = offset
    var size = length
    var code = status
    val headers = mutableMapOf("Accept-Ranges" to "bytes")
    range(ranges[id], length)?.let { (from, to) ->
      start += from
      size = to - from + 1
      code = 206
      headers["Content-Range"] = "bytes $from-$to/$length"
    }
    answer.complete(
      try {
        response(code, mime, Piece(path, start, size), size, headers)
      } catch (e: Exception) {
        response(500, "text/plain", ByteArrayInputStream(ByteArray(0)), 0, emptyMap())
      }
    )
  }

  fun destroy() {
    answers.values.forEach { it.cancel(true) }
    web.stopLoading()
    removeView(web)
    web.destroy()
  }

  private fun page() {
    onPage(
      mapOf(
        "url" to (web.url ?: ""),
        "title" to (web.title ?: ""),
        "back" to web.canGoBack(),
        "forward" to web.canGoForward(),
        "loading" to (web.progress < 100)
      )
    )
  }

  private inner class Pages : WebViewClient() {
    // Every file a page asks for: JavaScript answers on the main thread while this thread waits
    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
      if (!inside(request.url)) return response(403, "text/plain", ByteArrayInputStream(ByteArray(0)), 0, emptyMap())
      val id = count.incrementAndGet()
      val answer = CompletableFuture<WebResourceResponse>()
      answers[id] = answer
      request.requestHeaders.entries.firstOrNull { it.key.equals("Range", true) }?.let { ranges[id] = it.value }
      val ask = mapOf("id" to id, "url" to request.url.toString(), "main" to request.isForMainFrame)
      main.post { onAsk(ask) }
      return try {
        answer.get(30, TimeUnit.SECONDS)
      } catch (e: Exception) {
        Log.w("KitBooks", "no answer for ${request.url} ($e)")
        response(504, "text/plain", ByteArrayInputStream(ByteArray(0)), 0, emptyMap())
      } finally {
        answers.remove(id)
        ranges.remove(id)
      }
    }

    // The book's own pages load. A link out of it is the app's to offer; anything else going out is stopped.
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
      if (inside(request.url)) return false
      if (request.isForMainFrame && request.hasGesture()) onLeave(mapOf("url" to request.url.toString()))
      return true
    }

    override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) = page()

    override fun onPageFinished(view: WebView, url: String?) = page()

    override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) = page()

    // Android ended the page's process (low on memory): the app stays up, and the reader opens the book again
    override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
      onPage(mapOf("url" to "", "title" to "", "back" to false, "forward" to false, "loading" to false, "gone" to true))
      return true
    }
  }

  // A piece of a book's file, read as the page takes it
  private class Piece(path: String, start: Long, private var left: Long) : InputStream() {
    private val file = RandomAccessFile(path, "r").apply { seek(start) }

    override fun read(): Int {
      if (left <= 0) return -1
      val b = file.read()
      if (b >= 0) left--
      return b
    }

    override fun read(b: ByteArray, off: Int, len: Int): Int {
      if (left <= 0) return -1
      val n = file.read(b, off, minOf(len.toLong(), left).toInt())
      if (n > 0) left -= n
      return n
    }

    override fun close() = file.close()
  }

  companion object {
    const val HOST = ".zim.tinfoilkit.invalid"
    const val POLICY = "default-src 'self' data: blob: 'unsafe-inline' 'unsafe-eval'"

    fun inside(url: Uri) = url.scheme == "https" && (url.host ?: "").endsWith(HOST)

    fun response(status: Int, mime: String, body: InputStream, length: Long, extra: Map<String, String>): WebResourceResponse {
      val type = mime.substringBefore(";").trim()
      val charset = Regex("charset=([^;]+)", RegexOption.IGNORE_CASE).find(mime)?.groupValues?.get(1)?.trim()
      val headers = extra + mapOf("Content-Length" to length.toString(), "Content-Security-Policy" to POLICY)
      val reason = when (status) {
        200 -> "OK"
        206 -> "Partial Content"
        403 -> "Forbidden"
        404 -> "Not Found"
        504 -> "Gateway Timeout"
        else -> "Error"
      }
      return WebResourceResponse(type, charset, status, reason, headers, body)
    }

    // The part of a file a player asks for: "bytes=a-b", "bytes=a-" or "bytes=-n"
    fun range(header: String?, length: Long): Pair<Long, Long>? {
      val m = Regex("""^bytes=(\d*)-(\d*)""").find(header ?: return null) ?: return null
      val from = m.groupValues[1].toLongOrNull()
      val to = m.groupValues[2].toLongOrNull()
      return when {
        length <= 0 -> null
        from != null && from < length && (to == null || to >= from) -> from to minOf(to ?: (length - 1), length - 1)
        from == null && to != null && to > 0 -> maxOf(0L, length - to) to length - 1
        else -> null
      }
    }
  }
}
