import SwiftUI

struct Theme {
    static let background = Color.white
    static let secondaryBackground = Color(white: 0.94)
    static let actionBackground = Color(white: 0.88)
}

struct ContentView: View {
    @StateObject var llamaState = LlamaState()
    @State private var multiLineText = ""
    @State private var showDeleteConfirm = false

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            // --- CENTER CONTENT ---
            if llamaState.messageLog.isEmpty {
                VStack(spacing: 4) {
                    Text("HOW CAN I")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                    Text("HELP YOU?")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                }
                .foregroundColor(.black)
            } else {
                ScrollView(.vertical, showsIndicators: false) {
                    ScrollViewReader { proxy in
                        VStack(alignment: .leading, spacing: 12) {
                            // Markdown-rendered text
                            Text(LocalizedStringKey(llamaState.messageLog))
                                .font(.system(size: 16, design: .rounded))
                                .foregroundColor(.black)
                                .lineSpacing(6)
                                .padding(20)
                                .frame(maxWidth: .infinity, alignment: .topLeading)
                            
                            if llamaState.isGenerating {
                                TypingIndicator()
                                    .padding(.horizontal, 20)
                                    .padding(.bottom, 20)
                            }
                        }
                        .onChange(of: llamaState.messageLog) { _ in
                             withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
                        }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                }
            }

            Spacer()

            // --- MINIMALIST INPUT AREA ---
            VStack(spacing: 16) {
                // Input Card
                VStack(alignment: .leading, spacing: 12) {
                    TextField("Message", text: $multiLineText)
                        .font(.system(size: 16, weight: .medium, design: .rounded))
                        .foregroundColor(.black)
                    
                    HStack {
                        // Menu button (replaces plain '+' icon)
                        Menu {
                            Button(action: {
                                llamaState.showThinking.toggle()
                            }) {
                                Label(llamaState.showThinking ? "Hide Thoughts" : "Show Thoughts", systemImage: llamaState.showThinking ? "brain" : "brain.head.profile")
                            }
                            
                            Button(action: {
                                Task { await llamaState.clear() }
                            }) {
                                Label("Clear Chat", systemImage: "trash")
                            }
                            
                            Button(role: .destructive, action: {
                                showDeleteConfirm = true
                            }) {
                                Label("Delete Model", systemImage: "xmark.bin")
                            }
                        } label: {
                            Image(systemName: "plus")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundColor(.black)
                                .frame(width: 32, height: 32)
                                .background(Theme.actionBackground)
                                .clipShape(Circle())
                        }
                        
                        Spacer()
                        
                        if llamaState.isGenerating {
                            Button(action: { llamaState.stopGeneration() }) {
                                Image(systemName: "stop.circle.fill")
                                    .font(.system(size: 32))
                                    .foregroundColor(.black)
                            }
                        } else if llamaState.isModelLoaded && !multiLineText.isEmpty {
                            Button(action: sendText) {
                                Image(systemName: "arrow.up.circle.fill")
                                    .font(.system(size: 32))
                                    .foregroundColor(.black)
                            }
                        }
                    }
                }
                .padding(16)
                .background(Theme.secondaryBackground)
                .cornerRadius(24)
                .padding(.horizontal, 20)

                // Engine Lifecycle Pill
                if !llamaState.isModelLoaded {
                    IntelligencePill(llamaState: llamaState)
                }
                
                // Fine-print status
                Text(llamaState.isModelLoaded ? "ASBESTOS IS READY" : "OFFLINE")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundColor(.gray)
                    .tracking(1)
            }
            .padding(.bottom, 20)
        }
        .background(Theme.background)
        .alert("Delete Model?", isPresented: $showDeleteConfirm) {
            Button("Cancel", role: .cancel) { }
            Button("Delete", role: .destructive) {
                llamaState.deleteModel()
            }
        } message: {
            Text("This will remove the downloaded model from your device. You can re-download it later.")
        }
    }

    func sendText() {
        let text = multiLineText
        multiLineText = ""
        Task {
            await llamaState.complete(text: text)
        }
    }
}

struct IntelligencePill: View {
    @ObservedObject var llamaState: LlamaState
    @State private var progress: Double = 0
    @State private var isDownloading = false
    @State private var observation: NSKeyValueObservation?

    var body: some View {
        Group {
            if isDownloading {
                Text("INSTALLING \(Int(progress * 100))%")
            } else if let model = llamaState.undownloadedModels.first {
                Button("INSTALL Qwen3.5-0.8B-Q8_0") {
                    startDownload(model: model)
                }
            } else if let model = llamaState.downloadedModels.first {
                Button("INITIALIZE") {
                    let fileURL = llamaState.getDocumentsDirectory().appendingPathComponent(model.filename)
                    try? llamaState.loadModel(modelUrl: fileURL)
                }
            }
        }
        .font(.system(size: 11, weight: .black))
        .foregroundColor(.white)
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(Color.black)
        .clipShape(Capsule())
    }

    func startDownload(model: Model) {
        isDownloading = true
        guard let url = URL(string: model.url) else { return }
        let fileURL = llamaState.getDocumentsDirectory().appendingPathComponent(model.filename)
        
        let task = URLSession.shared.downloadTask(with: url) { temporaryURL, response, error in
            if let temp = temporaryURL {
                try? FileManager.default.copyItem(at: temp, to: fileURL)
                Task { @MainActor in 
                    isDownloading = false
                    try? llamaState.loadModel(modelUrl: fileURL)
                }
            }
        }
        
        observation = task.progress.observe(\.fractionCompleted) { p, _ in
            Task { @MainActor in
                self.progress = p.fractionCompleted
            }
        }
        
        task.resume()
    }
}

struct TypingIndicator: View {
    @State private var op: Double = 0.2
    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(Color.black).frame(width: 4, height: 4)
            Circle().fill(Color.black).frame(width: 4, height: 4)
            Circle().fill(Color.black).frame(width: 4, height: 4)
        }
        .opacity(op)
        .onAppear {
            withAnimation(.easeInOut(duration: 0.6).repeatForever()) {
                op = 1.0
            }
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
