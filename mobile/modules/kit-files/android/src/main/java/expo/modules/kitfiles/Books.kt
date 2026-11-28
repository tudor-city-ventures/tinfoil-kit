package expo.modules.kitfiles

import android.app.DownloadManager
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import com.github.luben.zstd.ZstdInputStreamNoFinalizer
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.concurrent.thread

class BookOptions : Record {
  @Field val id: String = "" // this download's own id
  @Field val book: String = ""
  @Field val title: String = "" // shown while it downloads
  @Field val url: String = ""
  @Field val incoming: String = "" // where it lands to be checked
  @Field val path: String = "" // where it goes once it's checked
  @Field val sha256: String? = null
  @Field val cellular: Boolean = false
  @Field val headers: Map<String, String> = emptyMap() // a kit at home's access code
}

// A book's download, kept as a file from when it starts until the app has seen how it went
private data class Book(
  val id: String,
  val book: String,
  val incoming: String,
  val path: String,
  val sha256: String?,
  val cellular: Boolean,
  val download: Long, // Android's downloader's id for it
  val state: String = "downloading", // then downloaded (being checked), then ready or failed
  val error: String? = null,
) {
  fun json(): String = JSONObject()
    .put("id", id).put("book", book).put("incoming", incoming).put("path", path).put("sha256", sha256 ?: "")
    .put("cellular", cellular).put("download", download).put("state", state).put("error", error ?: "")
    .toString()

  fun row(): Map<String, Any?> = mapOf("id" to id, "book" to book, "state" to state, "error" to (error ?: ""), "cellular" to cellular)

  companion object {
    fun parse(text: String): Book? = try {
      val o = JSONObject(text)
      Book(
        o.getString("id"), o.getString("book"), o.getString("incoming"), o.getString("path"),
        o.optString("sha256").ifEmpty { null }, o.getBoolean("cellular"), o.getLong("download"),
        o.getString("state"), o.optString("error").ifEmpty { null },
      )
    } catch (e: Exception) {
      null
    }
  }
}

// Books download with the app closed, by Android's own downloader, and each is checked against its SHA-256 and filed
// in the library as soon as it lands: Android tells the app when one does, even if the app was closed (BookDone), and
// a job checks it (BookCheck). It waits for Wi-Fi unless the person allows mobile data: the downloader then takes only
// an unmetered network, which leaves out a phone's hotspot.
class Books private constructor(private val context: Context) {
  companion object {
    private const val CHECK_JOB = 0x6b697431

    @Volatile private var instance: Books? = null

    fun get(context: Context): Books = instance ?: synchronized(this) {
      instance ?: Books(context.applicationContext).also { instance = it }
    }

    // A file's SHA-256, a megabyte at a time. Null when stopped first.
    fun sha256(file: File, stop: () -> Boolean = { false }): String? {
      val digest = MessageDigest.getInstance("SHA-256")
      file.inputStream().use { input ->
        val buffer = ByteArray(1 shl 20)
        while (true) {
          if (stop()) return null
          val n = input.read(buffer)
          if (n < 0) break
          digest.update(buffer, 0, n)
        }
      }
      return digest.digest().joinToString("") { "%02x".format(it) }
    }
  }

  private val manager = context.getSystemService(DownloadManager::class.java)
  private val records = File(context.filesDir, "books").apply { mkdirs() }
  private val lock = Any()

  // Books go in the app's own folder on the phone's shared storage, since Android's downloader can't write to the
  // app's private one. Other apps can't open it, and it goes when the app does.
  val library: File get() = File(context.getExternalFilesDir(null) ?: context.filesDir, "library")

  fun start(o: BookOptions) {
    val incoming = File(o.incoming)
    incoming.parentFile?.mkdirs()
    incoming.delete() // the downloader won't write over a file
    val request = DownloadManager.Request(Uri.parse(if (o.headers.isEmpty()) mirror(o.url) else o.url))
      .apply { o.headers.forEach { (name, value) -> addRequestHeader(name, value) } }
      .setDestinationUri(Uri.fromFile(incoming))
      .setAllowedOverMetered(o.cellular)
      .setAllowedOverRoaming(o.cellular)
      .setTitle(o.title)
      .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
    save(Book(o.id, o.book, o.incoming, o.path, o.sha256, o.cellular, manager.enqueue(request)))
    Log.i("KitBooks", "${o.id}: started, mobile data ${if (o.cellular) "allowed" else "not allowed"}")
  }

  fun stop(id: String) {
    val book = saved().firstOrNull { it.id == id } ?: return
    record(id).delete()
    if (book.state == "downloading") manager.remove(book.download) // and the part that came
  }

  fun forget(id: String) {
    record(id).delete()
  }

  // Every book download this knows of: the ones still downloading, and the ones that landed since the app last looked
  fun list(): List<Map<String, Any?>> {
    for (book in saved()) if (book.state == "downloading") landed(book.download) // in case Android's word was missed
    checkLater()
    return saved().map { book ->
      val now = if (book.state == "downloading") progress(book.download) else null
      if (now == null) {
        book.row()
      } else {
        book.row() + mapOf("received" to now.first.toDouble(), "total" to now.second.toDouble())
      }
    }
  }

  // Android's downloader is done with one: in the app's folder, or failed
  fun landed(download: Long) {
    synchronized(lock) {
      val book = saved().firstOrNull { it.download == download && it.state == "downloading" } ?: return
      val (now, reason) = status(download) ?: (DownloadManager.STATUS_FAILED to -1)
      when (now) {
        DownloadManager.STATUS_SUCCESSFUL -> save(book.copy(state = "downloaded"))
        DownloadManager.STATUS_FAILED -> {
          manager.remove(download)
          save(book.copy(state = "failed", error = message(reason)))
        }
        else -> return // still going
      }
      Log.i("KitBooks", "${book.id}: ${if (now == DownloadManager.STATUS_SUCCESSFUL) "landed" else message(reason)}")
    }
    checkLater()
  }

  // A job checks what's landed: it may take longer than Android gives the app for hearing that a download is done.
  // Scheduling it again would stop one that's running.
  fun checkLater() {
    val scheduler = context.getSystemService(JobScheduler::class.java)
    if (BookCheck.running || scheduler.getPendingJob(CHECK_JOB) != null) return
    if (saved().none { it.state == "downloaded" }) return
    scheduler.schedule(JobInfo.Builder(CHECK_JOB, ComponentName(context, BookCheck::class.java)).setOverrideDeadline(0).build())
  }

  // Until none is left, including any that land meanwhile
  fun checkAll(stop: () -> Boolean) {
    val tried = mutableSetOf<String>()
    while (!stop()) {
      val book = saved().firstOrNull { it.state == "downloaded" && it.id !in tried } ?: return
      tried.add(book.id)
      check(book, stop)
    }
  }

  private fun check(book: Book, stop: () -> Boolean) {
    val incoming = File(book.incoming)
    val done = try {
      if (!incoming.exists()) throw IOException("The download went missing")
      if (book.sha256 != null) {
        val got = sha256(incoming, stop) ?: return // stopped: the job runs again
        if (!got.equals(book.sha256, ignoreCase = true)) throw IOException("It came through damaged")
      }
      if (!record(book.id).exists()) {
        incoming.delete() // the app let it go while it was checked
        manager.remove(book.download)
        return
      }
      val path = File(book.path)
      path.parentFile?.mkdirs()
      path.delete()
      if (!incoming.renameTo(path)) throw IOException("It couldn't be put in the library")
      book.copy(state = "ready")
    } catch (e: Exception) {
      incoming.delete()
      book.copy(state = "failed", error = e.message ?: e.toString())
    }
    manager.remove(book.download) // the downloader's own record of it: its file has moved on, so nothing else goes
    synchronized(lock) { if (record(book.id).exists()) save(done) }
    Log.i("KitBooks", "${book.id}: ${done.state} ${done.error ?: ""}")
  }

  private fun status(download: Long): Pair<Int, Int>? =
    manager.query(DownloadManager.Query().setFilterById(download)).use { c ->
      if (!c.moveToFirst()) return null
      c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)) to
        c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
    }

  private fun progress(download: Long): Pair<Long, Long>? =
    manager.query(DownloadManager.Query().setFilterById(download)).use { c ->
      if (!c.moveToFirst()) return null
      c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)) to
        maxOf(c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)), 0L)
    }

  private fun message(reason: Int): String = when (reason) {
    401 -> "The kit's access code has changed"
    404, 410 -> "The file isn't there any more"
    DownloadManager.ERROR_INSUFFICIENT_SPACE -> "Not enough free space"
    DownloadManager.ERROR_CANNOT_RESUME -> "It couldn't pick up where it stopped"
    DownloadManager.ERROR_HTTP_DATA_ERROR -> "The connection kept dropping"
    -1 -> "The download was stopped"
    in 400..599 -> "The server said $reason"
    else -> "The download failed ($reason)"
  }

  // Kiwix's address sends each download on to a mirror. Asking the mirror itself means a download that picks up again
  // after a dropped connection asks the same one, for the same file.
  private fun mirror(url: String): String {
    var at = url
    repeat(5) {
      val conn = URL(at).openConnection() as HttpURLConnection
      try {
        conn.requestMethod = "HEAD"
        conn.instanceFollowRedirects = false
        conn.connectTimeout = 15_000
        conn.readTimeout = 15_000
        val next = conn.getHeaderField("Location")
        if (conn.responseCode !in 300..399 || next == null) return at
        at = URL(URL(at), next).toString()
      } catch (e: IOException) {
        return at
      } finally {
        conn.disconnect()
      }
    }
    return at
  }

  private fun record(id: String) = File(records, id.replace('/', '_') + ".json")

  private fun save(book: Book) {
    val tmp = File(records, ".${book.id.replace('/', '_')}.tmp")
    tmp.writeText(book.json())
    tmp.renameTo(record(book.id))
  }

  private fun saved(): List<Book> =
    records.listFiles { f -> f.name.endsWith(".json") }?.mapNotNull { Book.parse(it.readText()) } ?: emptyList()
}

// A book from a file, such as one sent with Quick Share or picked in Downloads: copied to where the app says, and
// checked as it comes against the MD5 checksum that ends every ZIM file, so a book that came through damaged or cut
// short never reaches the library. One at a time.
object Adding {
  @Volatile var done = 0L // bytes of it copied and checked
  @Volatile var total = 0L

  fun add(context: Context, from: String, to: File): Long {
    done = 0
    total = 0
    val uri = Uri.parse(from)
    val input = (if (uri.scheme == "content") context.contentResolver.openInputStream(uri) else File(uri.path ?: from).inputStream())
      ?: throw Failure("ERR_FILE", "The file couldn't be opened")
    to.parentFile?.mkdirs()
    try {
      input.use { inp ->
        to.outputStream().use { out ->
          // The header says where the checksum is: the last 16 bytes, the MD5 of all before them
          val header = ByteArray(80)
          var got = 0
          while (got < 80) got += inp.read(header, got, 80 - got).takeIf { it >= 0 } ?: break
          if (got < 80 || le(header, 0, 4) != 72173914L) throw Failure("ERR_NOT_A_BOOK", "This file isn't a book")
          val end = le(header, 72, 8)
          if (end < 80) throw Failure("ERR_DAMAGED", "It came through damaged")
          total = end + 16
          val md5 = MessageDigest.getInstance("MD5")
          md5.update(header)
          out.write(header)
          val want = ByteArray(16)
          var kept = 0
          var at = 80L
          val buffer = ByteArray(1 shl 20)
          while (true) {
            val n = inp.read(buffer)
            if (n < 0) break
            out.write(buffer, 0, n)
            val hashed = (end - at).coerceIn(0, n.toLong()).toInt()
            md5.update(buffer, 0, hashed)
            if (n > hashed) {
              if (kept + n - hashed > 16) throw Failure("ERR_DAMAGED", "It came through damaged")
              System.arraycopy(buffer, hashed, want, kept, n - hashed)
              kept += n - hashed
            }
            at += n
            done = at
          }
          if (at != end + 16) throw Failure("ERR_DAMAGED", "It came through cut short")
          if (!md5.digest().contentEquals(want)) throw Failure("ERR_DAMAGED", "It came through damaged")
          return at
        }
      }
    } catch (e: Exception) {
      to.delete()
      if (e is Failure) throw e
      throw Failure("ERR_FILE", e.message ?: e.toString())
    }
  }

  // A checked book into its place in the library, over any file there
  fun move(from: String, to: String) {
    val target = File(to)
    target.delete()
    if (!File(from).renameTo(target)) throw Failure("ERR_FILE", "It couldn't be put in the library")
  }

  private fun le(b: ByteArray, at: Int, bytes: Int): Long =
    (0 until bytes).fold(0L) { n, i -> n or ((b[at + i].toLong() and 0xff) shl (8 * i)) }
}

// A cluster of a book's pages, a Zstandard frame in its file, decompressed by zstd's own decoder (zstd-jni's): the
// app's JavaScript one takes a few hundred milliseconds a cluster on a phone, this a few
object Clusters {
  private const val LIMIT = 256 shl 20 // far past any real cluster: a damaged or hostile book stops here

  fun unzstd(path: String, offset: Double, length: Double): ByteArray {
    if (!(offset >= 0 && length >= 0 && length < LIMIT)) throw Failure("ERR_DAMAGED", "The book is damaged")
    val frame = ByteArray(length.toInt())
    RandomAccessFile(path, "r").use {
      it.seek(offset.toLong())
      it.readFully(frame)
    }
    ZstdInputStreamNoFinalizer(ByteArrayInputStream(frame)).use { z ->
      var out = ByteArray(minOf(maxOf(4 * frame.size, 1 shl 20), LIMIT))
      var n = 0
      while (true) {
        if (n == out.size) {
          if (out.size >= LIMIT) throw Failure("ERR_DAMAGED", "The book is damaged")
          out = out.copyOf(minOf(2 * out.size, LIMIT))
        }
        val got = z.read(out, n, out.size - n) // a frame cut short throws
        if (got < 0) return out.copyOf(n)
        n += got
      }
    }
  }
}

// Android's downloader says one is done, even with the app closed
class BookDone : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    val download = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1)
    if (download < 0) return
    val result = goAsync()
    thread {
      try {
        Books.get(context).landed(download)
      } finally {
        result.finish()
      }
    }
  }
}

class BookCheck : JobService() {
  companion object {
    @Volatile var running = false
  }

  @Volatile private var stopped = false

  override fun onStartJob(params: JobParameters): Boolean {
    stopped = false
    running = true
    thread {
      try {
        Books.get(this).checkAll { stopped }
      } finally {
        running = false
        jobFinished(params, false)
      }
    }
    return true
  }

  override fun onStopJob(params: JobParameters): Boolean {
    stopped = true
    return true // run it again later
  }
}
