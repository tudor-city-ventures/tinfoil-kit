#!/usr/bin/env bash
# Type-checks the phone app's native Android code (modules/*/android) in about a minute, without an Android build: a
# few lines below stand in for the Expo types the code uses, for Google's ML Kit as its reference describes it, which
# cloud machines can't download, and for the one class of zstd-jni the code uses. It only compiles, and leaves the
# files in Expo's module and view DSL (KitFilesModule.kt, BookView.kt) to CI's build. Needs a JDK, and Gradle or the
# app's packages (React Native's Gradle downloads itself). The first run downloads the Kotlin compiler and, without the
# Android SDK, Robolectric's copy of Android's classes: up to 300 MB.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="${TMPDIR:-/tmp}/tinfoilkit-check-android"
expo="$work/stubs/expo/modules/kotlin"
mlkit="$work/stubs/com/google/mlkit/genai"
zstd="$work/stubs/com/github/luben/zstd"
mkdir -p "$expo/exception" "$expo/records" "$mlkit/common" "$mlkit/prompt" "$zstd"

# Google's copy of Maven Central first: Maven Central itself often answers cloud machines with 429
repos='maven("https://maven-central.storage-download.googleapis.com/maven2"); mavenCentral()'
# Android's classes: from the Android SDK where there is one, as on GitHub's runners, else Robolectric's copy, which
# also has the ones Android hides from apps
jar="$(ls "${ANDROID_HOME:-/none}"/platforms/android-*/android.jar 2> /dev/null | sort -V | tail -1 || true)"
android='"org.robolectric:android-all:16-robolectric-13921718"'
if [ -n "$jar" ]; then android="files(\"$jar\")"; fi
cat > "$work/settings.gradle.kts" << EOF
pluginManagement { repositories { $repos; gradlePluginPortal() } }
rootProject.name = "check-android"
EOF
cat > "$work/build.gradle.kts" << EOF
plugins { kotlin("jvm") version "2.2.0" }
repositories { $repos }
dependencies { compileOnly($android); compileOnly("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2") }
sourceSets["main"].kotlin.setSrcDirs(listOf("stubs", "$here/modules"))
sourceSets["main"].kotlin.exclude("**/KitFilesModule.kt", "**/BookView.kt")
// Android's target, whatever JDK runs this: Java and Kotlin must agree, and this Kotlin can't target the newest JDKs
java { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
EOF
cat > "$expo/Promise.kt" << 'EOF'
package expo.modules.kotlin
import expo.modules.kotlin.exception.CodedException
interface Promise {
  fun resolve(value: Any?)
  fun resolve() = resolve(null)
  fun resolve(result: Double) = resolve(result as Any?)
  fun resolve(result: String) = resolve(result as Any?)
  fun resolve(result: Collection<Any?>) = resolve(result as Any?)
  fun resolve(result: Map<String, Any?>) = resolve(result as Any?)
  fun reject(code: String?, message: String?, cause: Throwable?)
  fun reject(exception: CodedException) = reject(exception.code, exception.message, exception.cause)
}
EOF
cat > "$expo/exception/CodedException.kt" << 'EOF'
package expo.modules.kotlin.exception
open class CodedException(message: String?, cause: Throwable? = null) : Exception(message, cause) {
  open val code: String = "ERR_UNKNOWN"
  constructor(code: String?, message: String?, cause: Throwable?) : this(message, cause)
}
EOF
cat > "$expo/records/Record.kt" << 'EOF'
package expo.modules.kotlin.records
interface Record
annotation class Field(val key: String = "")
EOF
cat > "$mlkit/common/Common.kt" << 'EOF'
package com.google.mlkit.genai.common
class GenAiException(message: String?) : Exception(message) {
  val errorCode: Int = 0
  annotation class ErrorCode { companion object { const val BUSY = 9 } }
}
annotation class FeatureStatus {
  companion object { const val UNAVAILABLE = 0; const val DOWNLOADABLE = 1; const val DOWNLOADING = 2; const val AVAILABLE = 3 }
}
sealed class DownloadStatus {
  data class DownloadStarted(val bytesToDownload: Long) : DownloadStatus()
  data class DownloadProgress(val totalBytesDownloaded: Long) : DownloadStatus()
  object DownloadCompleted : DownloadStatus()
  data class DownloadFailed(val e: GenAiException) : DownloadStatus()
}
EOF
cat > "$mlkit/prompt/Prompt.kt" << 'EOF'
package com.google.mlkit.genai.prompt
import com.google.mlkit.genai.common.DownloadStatus
import kotlinx.coroutines.flow.Flow
class TextPart(val text: String)
class Candidate(val text: String)
class GenerateContentResponse(val candidates: List<Candidate>)
class GenerateContentRequest {
  class Builder(text: TextPart) {
    var temperature: Float? = null
    var topK: Int? = null
    fun build() = GenerateContentRequest()
  }
}
fun generateContentRequest(text: TextPart, init: GenerateContentRequest.Builder.() -> Unit) =
  GenerateContentRequest.Builder(text).apply(init).build()
interface GenerativeModel {
  suspend fun checkStatus(): Int
  fun download(): Flow<DownloadStatus>
  suspend fun generateContent(request: GenerateContentRequest): GenerateContentResponse
  fun close()
}
object Generation {
  fun getClient(): GenerativeModel = throw NotImplementedError()
}
EOF
cat > "$zstd/ZstdInputStreamNoFinalizer.kt" << 'EOF'
package com.github.luben.zstd
open class ZstdInputStreamNoFinalizer(input: java.io.InputStream) : java.io.FilterInputStream(input)
EOF
gradle=gradle
command -v gradle > /dev/null || gradle="$here/node_modules/@react-native/gradle-plugin/gradlew"
cd "$work"
status=0
"$gradle" -q --no-daemon compileKotlin > out.log 2>&1 || status=$?
grep -v "^Picked up\|is deprecated\. Deprecated in Java" out.log || true # the JDK's own deprecations, not Android's
[ "$status" -eq 0 ] && echo "The Android code type-checks"
exit "$status"
