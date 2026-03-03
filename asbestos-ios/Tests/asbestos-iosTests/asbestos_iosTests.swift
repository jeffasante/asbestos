import XCTest
import llama
@testable import asbestos_ios

final class asbestos_iosTests: XCTestCase {
    func testFrameworkLoading() throws {
        // llama_backend_init() is the foundational call for llama.cpp
        llama_backend_init()
        print("  Llama backend initialized in Swift!")
        
        // Verify we can access default model params
        let params = llama_model_default_params()
        print("  Accessed llama_model_default_params. use_mmap: \(params.use_mmap)")
        
        XCTAssertTrue(params.use_mmap, "Default mmap should be enabled")
        
        llama_backend_free()
        print("  Llama backend freed.")
    }
}
