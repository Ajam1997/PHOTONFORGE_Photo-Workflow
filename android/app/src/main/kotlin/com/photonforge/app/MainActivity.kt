package com.photonforge.app

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.documentfile.provider.DocumentFile
import com.photonforge.app.pipeline.PipelineRunner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Phase 2 debug screen: pick the models directory + a photos directory, run the
 * headless pipeline, watch per-frame timings stream. No review UI yet (Phase 4).
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface(modifier = Modifier.fillMaxSize()) {
                    DebugScreen()
                }
            }
        }
    }

    @androidx.compose.runtime.Composable
    private fun DebugScreen() {
        var modelsUri by remember { mutableStateOf<Uri?>(null) }
        var photosUri by remember { mutableStateOf<Uri?>(null) }
        var running by remember { mutableStateOf(false) }
        var writeXmp by remember { mutableStateOf(true) }
        val lines = remember { mutableStateListOf<String>() }
        val scope = rememberCoroutineScope()
        val listState = rememberLazyListState()

        fun takePersist(uri: Uri) {
            contentResolver.takePersistableUriPermission(
                uri,
                android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        }

        val pickModels = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocumentTree(),
        ) { uri -> uri?.let { takePersist(it); modelsUri = it } }
        val pickPhotos = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocumentTree(),
        ) { uri -> uri?.let { takePersist(it); photosUri = it } }

        LaunchedEffect(lines.size) {
            if (lines.isNotEmpty()) listState.animateScrollToItem(lines.size - 1)
        }

        Column(modifier = Modifier.padding(16.dp)) {
            Text("PhotonForge — Phase 2 harness", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { pickModels.launch(null) }, enabled = !running) {
                    Text(if (modelsUri == null) "Pick models dir" else "Models ✓")
                }
                Button(onClick = { pickPhotos.launch(null) }, enabled = !running) {
                    Text(if (photosUri == null) "Pick photos dir" else "Photos ✓")
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Switch(checked = writeXmp, onCheckedChange = { writeXmp = it }, enabled = !running)
                Text("write XMP sidecars", modifier = Modifier.padding(top = 12.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Switch(checked = false, onCheckedChange = {}, enabled = false)
                Text("naming (Florence-2) — Phase 6, off", modifier = Modifier.padding(top = 12.dp))
            }
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = {
                    val m = modelsUri ?: return@Button
                    val p = photosUri ?: return@Button
                    running = true
                    lines.add("--- run started ---")
                    scope.launch(Dispatchers.Default) {
                        try {
                            val runner = PipelineRunner(this@MainActivity) { msg ->
                                scope.launch(Dispatchers.Main) { lines.add(msg) }
                            }
                            runner.run(
                                DocumentFile.fromTreeUri(this@MainActivity, p)!!,
                                DocumentFile.fromTreeUri(this@MainActivity, m)!!,
                                writeXmp = writeXmp,
                            )
                        } catch (e: Exception) {
                            scope.launch(Dispatchers.Main) { lines.add("RUN FAILED: $e") }
                        } finally {
                            scope.launch(Dispatchers.Main) { running = false }
                        }
                    }
                },
                enabled = !running && modelsUri != null && photosUri != null,
            ) {
                Text(if (running) "Running…" else "Run pipeline")
            }
            Spacer(Modifier.height(12.dp))
            LazyColumn(state = listState, modifier = Modifier.fillMaxWidth()) {
                items(lines) { line ->
                    Text(line, fontSize = 12.sp, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
