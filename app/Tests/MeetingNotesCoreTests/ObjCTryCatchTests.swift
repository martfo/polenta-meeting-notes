import Foundation
import Testing
import ObjCSupport

struct ObjCTryCatchTests {
    @Test("an Objective-C exception is caught and returned as an error")
    func test_catches_nsexception() {
        let error = ObjCTryCatch {
            NSException(name: .invalidArgumentException, reason: "boom", userInfo: nil).raise()
        }
        #expect(error != nil)
        #expect(error?.localizedDescription == "boom")
    }

    @Test("a block that does not throw returns no error")
    func test_no_exception_returns_nil() {
        var ran = false
        let error = ObjCTryCatch { ran = true }
        #expect(ran)
        #expect(error == nil)
    }
}
