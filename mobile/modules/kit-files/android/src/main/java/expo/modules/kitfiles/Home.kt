package expo.modules.kitfiles

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.io.RandomAccessFile
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Collections
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

// The kits shared on this Wi-Fi. Each says it's there by Bonjour, as _tinfoilkit._tcp under its computer's name (the
// kit's gate.go); a phone shared like one says kind=phone. Android resolves one service at a time, so the ones found
// wait their turn.
class KitFinder(context: Context) {
  private val nsd = context.getSystemService(NsdManager::class.java)
  private val main = Handler(Looper.getMainLooper())

  // What it finds in that many seconds: each kit's name, and where its gate answers
  fun find(seconds: Double, done: (List<Map<String, Any>>) -> Unit) {
    val found = linkedMapOf<String, Map<String, Any>>()
    val waiting = ArrayDeque<NsdServiceInfo>()
    var resolving = false
    var finished = false

    fun next() {
      if (resolving || finished) return
      val service = waiting.removeFirstOrNull() ?: return
      resolving = true
      @Suppress("DEPRECATION") // its replacement is Android 14's only
      nsd.resolveService(service, object : NsdManager.ResolveListener {
        override fun onServiceResolved(info: NsdServiceInfo) {
          @Suppress("DEPRECATION")
          val host = info.host
          main.post {
            if (host is Inet4Address) { // the kit answers on IPv4 only
              val phone = info.attributes["kind"]?.let { String(it, Charsets.UTF_8) } == "phone"
              found[info.serviceName] =
                mapOf("name" to info.serviceName, "host" to host.hostAddress!!, "port" to info.port, "phone" to phone)
            }
            resolving = false
            next()
          }
        }

        override fun onResolveFailed(info: NsdServiceInfo, error: Int) {
          main.post {
            resolving = false
            next()
          }
        }
      })
    }

    val discovery = object : NsdManager.DiscoveryListener {
      override fun onServiceFound(info: NsdServiceInfo) {
        main.post {
          if (!found.containsKey(info.serviceName) && waiting.none { it.serviceName == info.serviceName }) {
            waiting.addLast(info)
            next()
          }
        }
      }

      override fun onServiceLost(info: NsdServiceInfo) {}
      override fun onDiscoveryStarted(serviceType: String) {}
      override fun onDiscoveryStopped(serviceType: String) {}
      override fun onStartDiscoveryFailed(serviceType: String, error: Int) {}
      override fun onStopDiscoveryFailed(serviceType: String, error: Int) {}
    }

    nsd.discoverServices("_tinfoilkit._tcp", NsdManager.PROTOCOL_DNS_SD, discovery)
    main.postDelayed({
      finished = true
      try {
        nsd.stopServiceDiscovery(discovery)
      } catch (e: IllegalArgumentException) {
        // it never started
      }
      done(found.values.sortedBy { it["name"] as String })
    }, (seconds * 1000).toLong())
  }
}

class ShareOptions : Record {
  @Field val name: String = ""
  @Field val code: String = ""
  @Field val listing: String = "" // what /data/files answers: the books and the map, as a kit lists them
  @Field val files: Map<String, String> = emptyMap() // each file's path in the listing, and the file on this phone
  @Field val folders: Map<String, String> = emptyMap() // a folder's path in it (the map's fonts and icons), and here
}

// This phone shared like a kit at home, for another phone on the Wi-Fi to copy its books and map: what it serves, and
// why, is in Home.swift. On Android, a thread for each connection, and it stops when the share screen goes.
object Sharing {
  private const val KIT_PORT = 8000 // a kit's, so a typed address needs none
  private const val TRIES = 10 // wrong codes, then it stops: as many as a kit allows from one address in 10 minutes
  private const val MOST = 16 // connections at once
  private const val CHUNK = 256 shl 10
  private val allowed = Regex("[A-Za-z0-9 ._@,+-]+")

  private val lock = Any()
  private var server: ServerSocket? = null
  private var nsd: NsdManager? = null
  private var registration: NsdManager.RegistrationListener? = null
  @Volatile private var options = ShareOptions()
  private var port = 0
  private var wrong = 0
  private var stopped = "" // why it stopped by itself: "tries" (too many wrong codes)
  private val sent = AtomicLong()
  private val open: MutableSet<Socket> = Collections.synchronizedSet(mutableSetOf())
  private val asking: MutableSet<Socket> = Collections.synchronizedSet(mutableSetOf()) // being answered
  private val pool = Executors.newCachedThreadPool()

  // The port it listens on: a kit's, or any other if something else has that one
  fun start(context: Context, o: ShareOptions): Int = synchronized(lock) {
    halt()
    options = o
    wrong = 0
    stopped = ""
    sent.set(0)
    val socket = listen(KIT_PORT) ?: listen(0) ?: throw IOException("Can't share on this network")
    server = socket
    port = socket.localPort
    val app = context.applicationContext
    thread(name = "sharing", isDaemon = true) { accept(app, socket) }
    advertise(app, o.name, port)
    port
  }

  fun stop() = synchronized(lock) { halt() }

  fun state(context: Context): Map<String, Any> = synchronized(lock) {
    mapOf(
      "on" to (server != null),
      "port" to port,
      "addresses" to addresses(context),
      "sent" to sent.get().toDouble(),
      "copying" to asking.size,
      "stopped" to stopped,
    )
  }

  // On IPv4 only: 0.0.0.0
  private fun listen(port: Int): ServerSocket? {
    val socket = ServerSocket()
    return try {
      socket.reuseAddress = true // started again at once, on the same port
      socket.bind(InetSocketAddress(InetAddress.getByAddress(ByteArray(4)), port))
      socket
    } catch (e: IOException) {
      socket.close()
      null
    }
  }

  private fun advertise(context: Context, name: String, port: Int) {
    val nsd = context.getSystemService(NsdManager::class.java) ?: return
    val info = NsdServiceInfo().apply {
      serviceName = name
      serviceType = "_tinfoilkit._tcp"
      this.port = port
      setAttribute("v", "1")
      setAttribute("kind", "phone")
    }
    val listener = object : NsdManager.RegistrationListener {
      override fun onServiceRegistered(info: NsdServiceInfo) {}
      override fun onRegistrationFailed(info: NsdServiceInfo, error: Int) {}
      override fun onServiceUnregistered(info: NsdServiceInfo) {}
      override fun onUnregistrationFailed(info: NsdServiceInfo, error: Int) {}
    }
    nsd.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener)
    this.nsd = nsd
    registration = listener
  }

  // No more connections, and gone from Bonjour; ones under way carry on
  private fun stopListening() {
    try {
      server?.close()
    } catch (e: IOException) {
      // closed already
    }
    server = null
    registration?.let {
      try {
        nsd?.unregisterService(it)
      } catch (e: IllegalArgumentException) {
        // never registered
      }
    }
    registration = null
  }

  private fun halt() {
    stopListening()
    synchronized(open) { open.toList() }.forEach {
      try {
        it.close()
      } catch (e: IOException) {
        // gone already
      }
    }
  }

  private fun accept(context: Context, socket: ServerSocket) {
    while (true) {
      val client = try {
        socket.accept()
      } catch (e: IOException) {
        return // closed: sharing stopped
      }
      if (open.size >= MOST || mobile(context, client.localAddress)) {
        client.close()
        continue
      }
      open.add(client)
      pool.execute {
        try {
          client.use { answer(it) }
        } catch (e: Exception) {
          // the other phone went, or asked for something odd
        } finally {
          open.remove(client)
          asking.remove(client)
        }
      }
    }
  }

  // Whether a connection came over mobile data: sharing is for the Wi-Fi
  private fun mobile(context: Context, local: InetAddress): Boolean {
    val cm = context.getSystemService(ConnectivityManager::class.java) ?: return false
    @Suppress("DEPRECATION") // its replacement takes a callback
    val networks = cm.allNetworks
    return networks.any { n ->
      cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true &&
        cm.getLinkProperties(n)?.linkAddresses?.any { it.address == local } == true
    }
  }

  // This phone's addresses on the Wi-Fi
  private fun addresses(context: Context): List<String> {
    val cm = context.getSystemService(ConnectivityManager::class.java) ?: return emptyList()
    @Suppress("DEPRECATION")
    val networks = cm.allNetworks
    return networks
      .filter { n ->
        cm.getNetworkCapabilities(n)?.run {
          hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        } == true
      }
      .flatMap { n -> cm.getLinkProperties(n)?.linkAddresses.orEmpty() }
      .mapNotNull { (it.address as? Inet4Address)?.hostAddress }
      .distinct()
  }

  private fun answer(client: Socket) {
    client.soTimeout = 10_000 // one that asks for nothing goes, so it can't keep others out
    val head = readHead(BufferedInputStream(client.getInputStream())) ?: return
    asking.add(client)
    val out = BufferedOutputStream(client.getOutputStream(), CHUNK)
    val lines = head.split("\r\n")
    val request = lines[0].split(" ")
    val fields = lines.drop(1).mapNotNull { line ->
      val colon = line.indexOf(':')
      if (colon < 0) null else line.substring(0, colon).trim().lowercase() to line.substring(colon + 1).trim()
    }.toMap()
    if (request.size != 3 || (request[0] != "GET" && request[0] != "HEAD")) {
      return reply(out, 405, """{"error": "only GET and HEAD"}""")
    }
    val bare = request[0] == "HEAD"
    val auth = fields["authorization"] ?: ""
    val given = if (auth.lowercase().startsWith("bearer ")) auth.substring(7).filter { it.isLetterOrDigit() } else ""
    if (given.isEmpty() || !MessageDigest.isEqual(given.toByteArray(), options.code.toByteArray())) {
      if (given.isNotEmpty()) wrongCode()
      return reply(out, 401, """{"error": "this needs the phone's code"}""", bare)
    }
    val path = request[1].substringBefore('?')
    val top = "/data/files"
    if (path == top) return reply(out, 200, options.listing, bare)
    val file = if (path.startsWith("$top/")) local(path.substring(top.length + 1)) else null
    if (file == null || !file.isFile) return reply(out, 404, """{"error": "not shared"}""", bare)
    serve(out, file, fields, bare)
  }

  private fun wrongCode() = synchronized(lock) {
    if (++wrong >= TRIES && server != null) {
      stopped = "tries" // no more tries: the person starts again, with a new code
      stopListening()
    }
  }

  // The request's head, up to the blank line, or null if it doesn't come
  private fun readHead(input: InputStream): String? {
    val head = ByteArrayOutputStream()
    var last = 0
    while (head.size() < 8192) {
      val b = input.read()
      if (b < 0) return null
      head.write(b)
      last = (last shl 8) or b
      if (last == 0x0D0A0D0A) return String(head.toByteArray(), 0, head.size() - 4, Charsets.UTF_8)
    }
    return null
  }

  // The file on this phone that a path in the listing names: one of its files, or one in a folder it names
  private fun local(encoded: String): File? {
    val path = try {
      URLDecoder.decode(encoded.replace("+", "%2B"), "UTF-8")
    } catch (e: IllegalArgumentException) {
      return null
    }
    val o = options
    o.files[path]?.let { return File(it) }
    for ((folder, dir) in o.folders) {
      if (!path.startsWith("$folder/")) continue
      val rest = path.substring(folder.length + 1)
      val plain = rest.split("/").all { it.isNotEmpty() && !it.startsWith(".") && allowed.matches(it) }
      return if (plain) File(dir, rest) else null
    }
    return null
  }

  private fun serve(out: OutputStream, file: File, fields: Map<String, String>, bare: Boolean) {
    val size = file.length()
    val modified = file.lastModified()
    val tag = "\"$size-${modified / 1000}\""
    val date = SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss 'GMT'", Locale.US)
      .apply { timeZone = TimeZone.getTimeZone("GMT") }
      .format(Date(modified))
    var from = 0L
    var to = size - 1
    var status = 200
    val range = fields["range"]
    // a range, unless it's of another version of the file than this
    if (range != null && (fields["if-range"]?.let { it == tag || it == date } ?: true)) {
      val r = byteRange(range, size) ?: return reply(out, 416, "", bare, mapOf("Content-Range" to "bytes */$size"))
      from = r.first
      to = r.second
      status = 206
    }
    val extra = mutableMapOf("Accept-Ranges" to "bytes", "ETag" to tag, "Last-Modified" to date)
    if (status == 206) extra["Content-Range"] = "bytes $from-$to/$size"
    val length = to - from + 1
    out.write(head(status, "application/octet-stream", length, extra))
    if (!bare) {
      RandomAccessFile(file, "r").use { f ->
        f.seek(from)
        val buffer = ByteArray(CHUNK)
        var left = length
        while (left > 0) {
          val n = f.read(buffer, 0, minOf(left, CHUNK.toLong()).toInt())
          if (n < 0) break // shorter than it was: the other phone sees its copy end early
          out.write(buffer, 0, n)
          sent.addAndGet(n.toLong())
          left -= n
        }
      }
    }
    out.flush()
  }

  private fun reply(
    out: OutputStream,
    status: Int,
    body: String,
    bare: Boolean = false,
    extra: Map<String, String> = emptyMap(),
  ) {
    val bytes = body.toByteArray()
    out.write(head(status, "application/json", bytes.size.toLong(), extra))
    if (!bare) out.write(bytes)
    out.flush()
  }

  private fun head(status: Int, type: String, length: Long, extra: Map<String, String>): ByteArray {
    val reasons = mapOf(
      200 to "OK",
      206 to "Partial Content",
      401 to "Unauthorized",
      404 to "Not Found",
      405 to "Method Not Allowed",
      416 to "Range Not Satisfiable",
    )
    val s = StringBuilder("HTTP/1.1 $status ${reasons[status] ?: ""}\r\n")
    s.append("Content-Type: $type\r\nContent-Length: $length\r\n")
    for ((name, value) in extra) s.append("$name: $value\r\n")
    s.append("Cache-Control: no-store\r\nConnection: close\r\n\r\n")
    return s.toString().toByteArray()
  }

  // A Range header's one range in a file of that size, or null when it asks for none this answers
  private fun byteRange(header: String, size: Long): Pair<Long, Long>? {
    if (!header.startsWith("bytes=") || header.contains(',')) return null
    val ends = header.substring(6).split("-", limit = 2).map { it.trim() }
    if (ends.size != 2) return null
    if (ends[0].isEmpty()) { // the last n bytes
      val n = ends[1].toLongOrNull() ?: return null
      return if (n > 0 && size > 0) maxOf(0L, size - n) to size - 1 else null
    }
    val from = ends[0].toLongOrNull() ?: return null
    if (from < 0 || from >= size) return null
    if (ends[1].isEmpty()) return from to size - 1
    val to = ends[1].toLongOrNull() ?: return null
    return if (to >= from) from to minOf(to, size - 1) else null
  }
}
