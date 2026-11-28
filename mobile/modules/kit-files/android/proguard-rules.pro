# zstd-jni's native code looks up its classes' fields by name, and its package brings no rules of its own: without
# this, the release build renames them and the app stops at the first book page it unpacks (Clusters in Books.kt)
-keep class com.github.luben.zstd.** { *; }
