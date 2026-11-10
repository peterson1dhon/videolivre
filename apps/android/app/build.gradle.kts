import java.net.URI
import java.security.MessageDigest

plugins {
    id("com.android.application") version "8.13.2"
    id("org.jetbrains.kotlin.android") version "2.2.21"
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.21"
}

val nativePackages by configurations.creating
val engineVersion = "2026.10.26"
val abis = listOf("arm64-v8a", "x86_64")
val generated = layout.buildDirectory.dir("generated/localEngine")
val prepareLocalEngine by tasks.registering {
    inputs.files(nativePackages)
    inputs.property("engineVersion", engineVersion)
    inputs.property("abis", abis)
    outputs.dir(generated)

    doLast {
        val root = generated.get().asFile
        root.deleteRecursively()
        fun verify(file: File, sha256: String) {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val bytes = ByteArray(64 * 1024)
                while (true) {
                    val count = input.read(bytes)
                    if (count == -1) break
                    digest.update(bytes, 0, count)
                }
            }
            check(digest.digest().joinToString("") { "%02x".format(it) } == sha256) {
                "SHA-256 inválido para ${file.name}"
            }
        }
        fun fetch(name: String, url: String, sha256: String) {
            val file = root.resolve("assets/$name")
            file.parentFile.mkdirs()
            val connection = URI(url).toURL().openConnection()
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            connection.getInputStream().use { input -> file.outputStream().use { input.copyTo(it) } }
            verify(file, sha256)
        }

        nativePackages.forEach { archive ->
            val python = archive.name.startsWith("library-")
            verify(archive, if (python) {
                "579b5fb480892b1abc2b218c2089699d52759cc8d7ba256bf876453f0365faef"
            } else {
                "0a87ffa6cf912b0fe76c1a99b9107f543ee2f247935fae2c71f0822eb7bc5f49"
            })
            // Take only the standalone programs and their data, without the AAR's JVM code.
            copy {
                from(zipTree(archive))
                include(abis.map { "jni/$it/*.so" })
                into(root)
            }
        }
        fetch("yt-dlp", "https://github.com/yt-dlp/yt-dlp/releases/download/$engineVersion/yt-dlp",
            "e51e69e89489f199530f13d32a4342da3ddb2cf34842f364603a066db05afbf3")
        fetch("yt_dlp_ejs.whl", "https://files.pythonhosted.org/packages/e3/bd/520769863744b669440a924271a6159ddd82ad5ae26b4ac4d4b69e9f8d44/yt_dlp_ejs-0.8.0-py3-none-any.whl",
            "79300e5fca7f937a1eeede11f0456862c1b41107ce1d726871e0207424f4bdb4")
    }
}

android {
    namespace = "br.com.videolivre.android"
    compileSdk = 36
    defaultConfig {
        applicationId = "br.com.videolivre.android"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "ENGINE_VERSION", "\"$engineVersion\"")
    }

    splits {
        abi {
            isEnable = true
            reset()
            include(*abis.toTypedArray())
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging.jniLibs {
        useLegacyPackaging = true
        keepDebugSymbols += "**/lib*.so"
    }
    sourceSets["main"].apply {
        assets.srcDir(generated.map { it.dir("assets") })
        jniLibs.srcDir(generated.map { it.dir("jni") })
    }
}

tasks.named("preBuild").configure { dependsOn(prepareLocalEngine) }

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
    nativePackages("io.github.junkfood02.youtubedl-android:library:0.18.1@aar")
    nativePackages("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1@aar")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3:1.3.2")
    testImplementation("junit:junit:4.13.2")
}
