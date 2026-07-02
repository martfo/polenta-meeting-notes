// Test inventory for sections 3.1, 3.2, and 3.3 (app side). Stubs are filled
// in as phase 3 is built and must stay green after.

import Testing
@testable import MeetingNotesCore

struct AC_3_ProvisioningAndVaultTests {
    @Test("AC-3.1-a first-run detection by runtime presence and validity",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_1_a_first_run_detection() {}

    @Test("AC-3.1-b provisioning resumes over a partial runtime",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_1_b_provisioning_resumes() {}

    @Test("AC-3.1-c provisioning failure is a clear, retryable state",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_1_c_provisioning_failure_retryable() {}

    @Test("AC-3.1-d runtime path under Application Support, separate from the vault",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_1_d_runtime_path() {}

    @Test("AC-3.2-a vault creation makes the folders, prompt, and config",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_2_a_vault_creation() {}

    @Test("AC-3.2-b opening an existing vault overwrites nothing",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_2_b_existing_vault_untouched() {}

    @Test("AC-3.3-a entitlements and usage strings are declared",
          .disabled("stub: phase 3 not yet built"))
    func test_ac_3_3_a_entitlements_declared() {}
}
