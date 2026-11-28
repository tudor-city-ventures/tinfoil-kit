package expo.modules.kitfiles

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.google.mlkit.genai.common.DownloadStatus
import com.google.mlkit.genai.common.FeatureStatus
import com.google.mlkit.genai.common.GenAiException
import com.google.mlkit.genai.prompt.Generation
import com.google.mlkit.genai.prompt.GenerativeModel
import com.google.mlkit.genai.prompt.TextPart
import com.google.mlkit.genai.prompt.generateContentRequest
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.firstOrNull

// The AI built into the phone, where there is one: Google's Gemini Nano, which Android's AICore keeps for every app on
// the phone to share, asked through ML Kit's Prompt API. A phone that can have it but hasn't yet gets it from Google
// when an app asks: this one asks only when the person taps for it, and only on Wi-Fi unless mobile data is allowed.
class AI(private val context: () -> Context?) {
  private var client: GenerativeModel? = null

  @Synchronized
  private fun model() = client ?: Generation.getClient().also { client = it }

  // "ready", "downloadable" (the phone can have it, once asked for), "downloading", or "none": no AICore, or a phone
  // it doesn't run on
  suspend fun state(): String = try {
    when (model().checkStatus()) {
      FeatureStatus.AVAILABLE -> "ready"
      FeatureStatus.DOWNLOADABLE -> "downloadable"
      FeatureStatus.DOWNLOADING -> "downloading"
      else -> "none"
    }
  } catch (e: Exception) {
    "none"
  }

  // Asks for it, and returns once it's on the phone: AICore downloads it
  suspend fun download(cellular: Boolean) {
    val cm = context()?.getSystemService(ConnectivityManager::class.java) ?: throw Failure("ERR_OFFLINE", "No network")
    val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: throw Failure("ERR_OFFLINE", "No network")
    if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) throw Failure("ERR_OFFLINE", "No internet")
    if (!cellular && !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) {
      throw Failure("ERR_NOT_ON_WIFI", "Waiting for Wi-Fi") // mobile data, or a phone's hotspot
    }
    val end = model().download().firstOrNull { it is DownloadStatus.DownloadCompleted || it is DownloadStatus.DownloadFailed }
    if (end is DownloadStatus.DownloadFailed) throw Failure("ERR_AI_DOWNLOAD", end.e.message ?: "It didn't download")
  }

  // Its answer to the prompt, following the instructions, at the kit page's temperature. The instructions lead the
  // prompt: instructions of their own need a newer Gemini Nano than many phones have. It answers only while the app is
  // on screen, and one app at a time: busy with another, it's asked again.
  suspend fun answer(instructions: String, prompt: String): String {
    val request = generateContentRequest(TextPart("$instructions\n\n$prompt")) { temperature = 0.3f }
    var tries = 1
    while (true) {
      try {
        return model().generateContent(request).candidates.firstOrNull()?.text.orEmpty()
      } catch (e: GenAiException) {
        if (e.errorCode != GenAiException.ErrorCode.BUSY || tries == 3) throw e
        delay(1000L * tries++)
      }
    }
  }

  @Synchronized
  fun close() {
    client?.close()
    client = null
  }
}
