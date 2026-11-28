package expo.modules.kitfiles

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.util.Collections
import java.util.concurrent.Executors

class DownloadOptions : Record {
  @Field val url: String = ""
  @Field val path: String = ""
  @Field val cellular: Boolean = false
  @Field val headers: Map<String, String> = emptyMap() // a kit at home's access code
  @Field val offset: Double? = null
  @Field val length: Double? = null
  @Field val at: Double? = null
}

internal class Failure(code: String, message: String) : CodedException(code, message, null)

// Downloads while the app is open, written into a file as they come: a whole file, or one part of one. A part is taken
// only as asked for: a server that ignored the range would be sending the whole file, which for the world map is
// 120 GB, so anything but exactly those bytes stops at once. Over Wi-Fi only, unless mobile data is allowed: each
// connection is made on the network that was unmetered when it started, so it ends if that network goes, rather than
// carrying on over mobile data.
class Downloads(private val context: () -> Context?) {
  private val pool = Executors.newFixedThreadPool(6)
  private val open = Collections.synchronizedSet(mutableSetOf<HttpURLConnection>())
  @Volatile private var stops = 0

  fun start(o: DownloadOptions, promise: Promise) {
    val stopsAtStart = stops
    pool.execute {
      try {
        promise.resolve(download(o, stopsAtStart).toDouble())
      } catch (e: CodedException) {
        promise.reject(e)
      } catch (e: IOException) {
        promise.reject(
          if (stops != stopsAtStart) Failure("ERR_STOPPED", "Stopped") else Failure("ERR_OFFLINE", e.message ?: "The connection dropped")
        )
      } catch (e: Exception) {
        promise.reject(Failure("ERR_DOWNLOAD", e.message ?: e.toString()))
      }
    }
  }

  fun stop() {
    stops++
    synchronized(open) { open.toList() }.forEach { it.disconnect() }
  }

  private fun download(o: DownloadOptions, stopsAtStart: Int): Long {
    val cm = context()?.getSystemService(ConnectivityManager::class.java) ?: throw Failure("ERR_OFFLINE", "No network")
    val network = cm.activeNetwork ?: throw Failure("ERR_OFFLINE", "No network")
    val caps = cm.getNetworkCapabilities(network) ?: throw Failure("ERR_OFFLINE", "No network")
    if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) throw Failure("ERR_OFFLINE", "No internet")
    if (!o.cellular && !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) {
      throw Failure("ERR_NOT_ON_WIFI", "Waiting for Wi-Fi") // mobile data, or a phone's hotspot
    }
    val file = File(o.path)
    val range = if (o.offset != null && o.length != null && o.length > 0) {
      o.offset.toLong() to o.offset.toLong() + o.length.toLong() - 1
    } else {
      null
    }
    // into a file that's there already: one deleted since (its plan stopped) stays deleted
    if (o.at != null && !file.exists()) throw Failure("ERR_GONE", "The file it was going into is gone")
    val conn = network.openConnection(URL(o.url)) as HttpURLConnection
    open.add(conn)
    try {
      if (stops != stopsAtStart) throw Failure("ERR_STOPPED", "Stopped")
      conn.connectTimeout = 30_000
      conn.readTimeout = 30_000
      conn.useCaches = false
      conn.setRequestProperty("Accept-Encoding", "identity") // the file's own bytes, never unzipped ones
      o.headers.forEach { (name, value) -> conn.setRequestProperty(name, value) }
      if (range != null) conn.setRequestProperty("Range", "bytes=${range.first}-${range.second}")
      val status = conn.responseCode
      if (range != null) {
        if (status != 206) throw Failure(if (status == 200) "ERR_NO_RANGE" else "ERR_HTTP_$status", "The server said $status")
        // bytes from-to/size: from where asked, to where asked or the file's end before it
        val n = (conn.getHeaderField("Content-Range") ?: "").removePrefix("bytes ").split('-', '/').mapNotNull { it.toLongOrNull() }
        val whole = n.size == 3 && n[0] == range.first && (n[1] == range.second || (n[1] < range.second && n[1] == n[2] - 1))
        if (!whole) throw Failure("ERR_NO_RANGE", "The server sent other bytes than those asked for")
      } else if (status != 200) {
        throw Failure("ERR_HTTP_$status", "The server said $status")
      }
      if (o.at == null) file.parentFile?.mkdirs()
      val most = if (range != null) range.second - range.first + 1 else Long.MAX_VALUE
      var received = 0L
      RandomAccessFile(file, "rw").use { out ->
        if (o.at != null) out.seek(o.at.toLong()) else out.setLength(0)
        conn.inputStream.use { input ->
          val buffer = ByteArray(1 shl 16)
          while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            if (received + n > most) throw Failure("ERR_NO_RANGE", "The server sent more than was asked for")
            out.write(buffer, 0, n)
            received += n
          }
        }
      }
      return received
    } finally {
      open.remove(conn)
      conn.disconnect()
    }
  }
}
