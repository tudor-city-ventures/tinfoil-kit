package expo.modules.kitfiles

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import java.net.Inet4Address

// The kits shared on this Wi-Fi. Each says it's there by Bonjour, as _tinfoilkit._tcp under its computer's name (the
// kit's gate.go). Android resolves one service at a time, so the ones found wait their turn.
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
              found[info.serviceName] = mapOf("name" to info.serviceName, "host" to host.hostAddress!!, "port" to info.port)
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
