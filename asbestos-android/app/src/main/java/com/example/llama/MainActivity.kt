package com.example.llama

import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.addCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import com.arm.aichat.gguf.GgufMetadata
import com.arm.aichat.gguf.GgufMetadataReader
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    // Android views
    private lateinit var messagesRv: RecyclerView
    private lateinit var userInputEt: EditText
    private lateinit var userActionFab: android.view.View
    private lateinit var menuButton: android.view.View
    private lateinit var downloadFab: android.widget.Button
    private lateinit var statusIndicator: TextView
    private lateinit var welcomeContainer: android.view.View

    // Arm AI Chat inference engine
    private lateinit var engine: InferenceEngine
    private var generationJob: Job? = null
    private var showThoughts = false

    // Conversation states
    private var isModelReady = false
    private val messages = mutableListOf<Message>()
    private val messageHistory = mutableListOf<Pair<String, String>>()
    private val lastAssistantMsg = StringBuilder()
    private val messageAdapter = MessageAdapter(messages)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)
        // View model boilerplate and state management is out of this basic sample's scope
        onBackPressedDispatcher.addCallback { Log.w(TAG, "Ignore back press for simplicity") }

        // Find views
        messagesRv = findViewById(R.id.messages)
        messagesRv.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        messagesRv.adapter = messageAdapter
        userInputEt = findViewById(R.id.user_input)
        userActionFab = findViewById(R.id.fab)
        menuButton = findViewById(R.id.menu_button)
        downloadFab = findViewById(R.id.download_fab)
        statusIndicator = findViewById(R.id.statusIndicator)
        welcomeContainer = findViewById(R.id.welcome_container)

        menuButton.setOnClickListener { view ->
            val popup = android.widget.PopupMenu(this, view)
            popup.menuInflater.inflate(R.menu.chat_menu, popup.menu)

            // Update title based on current state
            val item = popup.menu.findItem(R.id.action_toggle_thoughts)
            item.title = if (showThoughts) "Hide Thoughts" else "Show Thoughts"

            popup.setOnMenuItemClickListener { menuItem ->
                when (menuItem.itemId) {
                    R.id.action_toggle_thoughts -> {
                        showThoughts = !showThoughts
                        true
                    }
                    else -> false
                }
            }
            popup.show()
        }

        checkInitialStatus()

        // Arm AI Chat initialization
        lifecycleScope.launch(Dispatchers.Default) {
            engine = AiChat.getInferenceEngine(applicationContext)
        }

        // Upon CTA button tapped
        userActionFab.setOnClickListener {
            if (isModelReady) {
                // If model is ready, validate input and send to engine
                handleUserInput()
            } else {
                // Otherwise, prompt user to select a GGUF metadata on the device
                getContent.launch(arrayOf("*/*"))
            }
        }

        // Upon Download button tapped
        downloadFab.setOnClickListener { handleDownload() }
    }

    private fun checkInitialStatus() {
        val fileName = Uri.parse(MODEL_URL).lastPathSegment ?: "model.gguf"
        val destinationFile = File(ensureModelsDirectory(), fileName)
        if (destinationFile.exists()) {
            downloadFab.text = "INITIALIZE"
            findViewById<TextView>(R.id.model_status_text).text = "Asbestos core verified"
        } else {
            downloadFab.text = "INSTALL"
            findViewById<TextView>(R.id.model_status_text).text =
                    "Asbestos core ready for installation"
        }
    }

    private fun handleDownload() {
        val modelUri = Uri.parse(MODEL_URL)
        val fileName = modelUri.lastPathSegment ?: "model.gguf"
        val modelsDir = ensureModelsDirectory()
        val destinationFile = File(modelsDir, fileName)

        if (destinationFile.exists()) {
            Toast.makeText(this, "Model already downloaded!", Toast.LENGTH_SHORT).show()
            handleLocalFile(Uri.fromFile(destinationFile))
            return
        }

        Toast.makeText(this, "Starting download...", Toast.LENGTH_SHORT).show()
        downloadFab.isEnabled = false
        downloadProgress.visibility = android.view.View.VISIBLE
        downloadProgress.progress = 0

        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val url = java.net.URL(MODEL_URL)
                val connection = url.openConnection()
                connection.connect()
                val fileLength = connection.contentLength

                // Check free space (approximate)
                val freeSpace = ensureModelsDirectory().usableSpace
                if (fileLength > freeSpace) {
                    throw java.io.IOException(
                            "Not enough space! Needed ${fileLength / 1024 / 1024}MB, available ${freeSpace / 1024 / 1024}MB"
                    )
                }

                url.openStream().use { input ->
                    destinationFile.outputStream().use { output ->
                        val buffer = ByteArray(8192)
                        var total: Long = 0
                        var count: Int
                        while (input.read(buffer).also { count = it } != -1) {
                            total += count
                            if (fileLength > 0) {
                                withContext(Dispatchers.Main) {
                                    downloadFab.text = "${(total * 100 / fileLength).toInt()}%"
                                }
                            }
                            output.write(buffer, 0, count)
                        }
                    }
                }
                withContext(Dispatchers.Main) {
                    downloadProgress.visibility = android.view.View.GONE
                    Toast.makeText(this@MainActivity, "Download complete!", Toast.LENGTH_LONG)
                            .show()
                    downloadFab.isEnabled = true
                    handleLocalFile(Uri.fromFile(destinationFile))
                }
            } catch (e: Exception) {
                Log.e(TAG, "Download failed", e)
                withContext(Dispatchers.Main) {
                    downloadProgress.visibility = android.view.View.GONE
                    Toast.makeText(
                                    this@MainActivity,
                                    "Download failed: ${e.localizedMessage}",
                                    Toast.LENGTH_LONG
                            )
                            .show()
                    downloadFab.isEnabled = true
                }
            }
        }
    }

    private fun handleLocalFile(uri: Uri) {
        handleSelectedModel(uri)
    }

    private val getContent =
            registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                Log.i(TAG, "Selected file uri:\n $uri")
                uri?.let { handleSelectedModel(it) }
            }

    /** Handles the file Uri from [getContent] result */
    private fun handleSelectedModel(uri: Uri) {
        // Update UI states
        userActionFab.isEnabled = false
        userInputEt.hint = "Reading model..."
        ggufTv.text = "Analyzing model file \n$uri"

        lifecycleScope.launch(Dispatchers.IO) {
            // Analyze model metadata
            Log.i(TAG, "Analyzing model metadata...")
            contentResolver
                    .openInputStream(uri)
                    ?.use { GgufMetadataReader.create().readStructuredMetadata(it) }
                    ?.let { metadata ->
                        // Update UI to show model details
                        Log.i(TAG, "Model analyzed: \n$metadata")
                        withContext(Dispatchers.Main) { ggufTv.text = metadata.toString() }

                        // Ensure the model file is available
                        val modelName = metadata.filename() + FILE_EXTENSION_GGUF
                        contentResolver
                                .openInputStream(uri)
                                ?.use { input -> ensureModelFile(modelName, input) }
                                ?.let { modelFile ->
                                    if (uri.scheme == "file") {
                                        // If it's already a local file in our models directory,
                                        // don't copy
                                        loadModel(modelName, modelFile)
                                    } else {
                                        contentResolver
                                                .openInputStream(uri)
                                                ?.use { input ->
                                                    // Check free space before copying
                                                    val needed = input.available()
                                                    val free = ensureModelsDirectory().usableSpace
                                                    if (needed > free) {
                                                        throw java.io.IOException(
                                                                "Not enough space to copy model!"
                                                        )
                                                    }
                                                    ensureModelFile(modelName, input)
                                                }
                                                ?.let { copiedFile ->
                                                    loadModel(modelName, copiedFile)
                                                }
                                    }

                                    withContext(Dispatchers.Main) {
                                        isModelReady = true
                                        userInputEt.hint = "Enter message"
                                        userInputEt.isEnabled = true
                                        userActionFab.isEnabled = true
                                        statusIndicator.text = "ASBESTOS IS READY"
                                        statusIndicator.setBackgroundResource(
                                                R.drawable.bg_status_ready
                                        )
                                        statusIndicator.setTextColor(android.graphics.Color.WHITE)
                                        downloadFab.text = "ACTIVE"
                                        downloadFab.isEnabled = false
                                        findViewById<TextView>(R.id.model_status_text).text =
                                                "Asbestos core initialized"
                                    }
                                }
                    }
        }
    }

    /** Prepare the model file within app's private storage */
    private suspend fun ensureModelFile(modelName: String, input: InputStream) =
            withContext(Dispatchers.IO) {
                File(ensureModelsDirectory(), modelName).also { file ->
                    // Copy the file into local storage if not yet done
                    if (!file.exists()) {
                        Log.i(TAG, "Start copying file to $modelName")
                        withContext(Dispatchers.Main) { userInputEt.hint = "Copying file..." }

                        FileOutputStream(file).use { input.copyTo(it) }
                        Log.i(TAG, "Finished copying file to $modelName")
                    } else {
                        Log.i(TAG, "File already exists $modelName")
                    }
                }
            }

    /** Load the model file from the app private storage */
    private suspend fun loadModel(modelName: String, modelFile: File) =
            withContext(Dispatchers.IO) {
                Log.i(TAG, "Loading model $modelName")
                withContext(Dispatchers.Main) { userInputEt.hint = "Loading model..." }
                engine.loadModel(modelFile.path)
            }

    /** Validate and send the user message into [InferenceEngine] */
    private fun handleUserInput() {
        userInputEt.text.toString().also { userMsg ->
            if (userMsg.isEmpty()) {
                Toast.makeText(this, "Input message is empty!", Toast.LENGTH_SHORT).show()
            } else {
                if (generationJob?.isActive == true) {
                    generationJob?.cancel()
                    userInputEt.isEnabled = true
                    (userActionFab as? ImageView)?.setImageResource(
                            R.drawable.outline_arrow_upward_24
                    )
                    return
                }

                userInputEt.text = null
                userInputEt.isEnabled = false
                (userActionFab as? ImageView)?.setImageResource(R.drawable.baseline_stop_24)

                // Update message states
                if (messages.isEmpty()) {
                    welcomeContainer.visibility = android.view.View.GONE
                    messagesRv.visibility = android.view.View.VISIBLE
                }
                messages.add(Message(UUID.randomUUID().toString(), userMsg, true))
                lastAssistantMsg.clear()
                messages.add(
                        Message(UUID.randomUUID().toString(), lastAssistantMsg.toString(), false)
                )

                generationJob =
                        lifecycleScope.launch(Dispatchers.Default) {
                            // Single-turn prompt — the 0.8B model echoes history with multi-turn
                            // Note: InferenceEngine handles ChatML formatting internally using the
                            // GGUF metadata
                            val systemPrompt = if (showThoughts)
                                "You are Asbestos, a helpful local AI assistant. Answer concisely."
                            else
                                "You are Asbestos, a helpful local AI assistant. Answer concisely. Do not use <think> tags. Respond directly."
                            engine.setSystemPrompt(systemPrompt)
                            engine.sendUserPrompt(userMsg, 4096)
                                    .onCompletion {
                                        withContext(Dispatchers.Main) {
                                            userInputEt.isEnabled = true
                                            (userActionFab as? ImageView)?.setImageResource(
                                                    R.drawable.outline_arrow_upward_24
                                            )
                                        }
                                    }
                                    .collect { token ->
                                        withContext(Dispatchers.Main) {
                                            val messageCount = messages.size
                                            check(
                                                    messageCount > 0 &&
                                                            !messages[messageCount - 1].isUser
                                            )

                                            if (token.contains("<|im_end|>") ||
                                                            token.contains("<|im_start|>")
                                            ) {
                                                coroutineContext.cancel()
                                                return@withContext
                                            }

                                            lastAssistantMsg.append(token)
                                            val cleanText =
                                                    sanitizeResponse(lastAssistantMsg.toString())

                                            messages.removeAt(messageCount - 1)
                                                    .copy(content = cleanText)
                                                    .let { messages.add(it) }

                                            messageAdapter.notifyItemChanged(messages.size - 1)
                                        }
                                    }
                        }
        }
    }

    private fun sanitizeResponse(raw: String): String {
        var cleaned = raw
        
        if (showThoughts) {
            cleaned = cleaned.replace("<think>", "\n💭 *Thinking:*\n")
                             .replace("</think>", "\n---\n")
        } else {
            // Handle complete think blocks — remove the thinking content entirely
            val regex = Regex("<think>[\\s\\S]*?</think>")
            cleaned = regex.replace(cleaned, "")
            
            // Handle incomplete think blocks (model is still thinking)
            if (cleaned.contains("<think>") && !cleaned.contains("</think>")) {
                val index = cleaned.indexOf("<think>")
                if (index != -1) {
                    cleaned = cleaned.substring(0, index) + "💭 *Thinking...*"
                }
            }
        }
        
        // Remove all ChatML control tags
        cleaned = cleaned.replace("<|im_end|>", "")
                .replace("<|im_start|>assistant", "")
                .replace("<|im_start|>user", "")
                .replace("<|im_start|>system", "")
                .replace("<|im_start|>", "")
                .replace("<|endoftext|>", "")
                
        // Trim leading and trailing whitespace
        cleaned = cleaned.trim()
        
        return cleaned
    }

    /** Run a benchmark with the model file */
    @Deprecated(
            "This benchmark doesn't accurately indicate GUI performance expected by app developers"
    )
    private suspend fun runBenchmark(modelName: String, modelFile: File) =
            withContext(Dispatchers.Default) {
                Log.i(TAG, "Starts benchmarking $modelName")
                withContext(Dispatchers.Main) { userInputEt.hint = "Running benchmark..." }
                engine.bench(
                                pp = BENCH_PROMPT_PROCESSING_TOKENS,
                                tg = BENCH_TOKEN_GENERATION_TOKENS,
                                pl = BENCH_SEQUENCE,
                                nr = BENCH_REPETITION
                        )
                        .let { result ->
                            messages.add(Message(UUID.randomUUID().toString(), result, false))
                            withContext(Dispatchers.Main) {
                                messageAdapter.notifyItemChanged(messages.size - 1)
                            }
                        }
            }

    /** Create the `models` directory if not exist. */
    private fun ensureModelsDirectory() =
            File(filesDir, DIRECTORY_MODELS).also {
                if (it.exists() && !it.isDirectory) {
                    it.delete()
                }
                if (!it.exists()) {
                    it.mkdir()
                }
            }

    override fun onStop() {
        generationJob?.cancel()
        super.onStop()
    }

    override fun onDestroy() {
        engine.destroy()
        super.onDestroy()
    }

    companion object {
        private val TAG = MainActivity::class.java.simpleName

        private const val DIRECTORY_MODELS = "models"
        private const val FILE_EXTENSION_GGUF = ".gguf"

        private const val MODEL_URL =
                "https://huggingface.co/bartowski/Qwen_Qwen3.5-0.8B-GGUF/resolve/main/Qwen_Qwen3.5-0.8B-Q8_0.gguf?download=true"

        private const val BENCH_PROMPT_PROCESSING_TOKENS = 512
        private const val BENCH_TOKEN_GENERATION_TOKENS = 128
        private const val BENCH_SEQUENCE = 1
        private const val BENCH_REPETITION = 3
    }
}

fun GgufMetadata.filename() =
        when {
            basic.name != null -> {
                basic.name?.let { name -> basic.sizeLabel?.let { size -> "$name-$size" } ?: name }
            }
            architecture?.architecture != null -> {
                architecture?.architecture?.let { arch ->
                    basic.uuid?.let { uuid -> "$arch-$uuid" }
                            ?: "$arch-${System.currentTimeMillis()}"
                }
            }
            else -> {
                "model-${System.currentTimeMillis().toHexString()}"
            }
        }
