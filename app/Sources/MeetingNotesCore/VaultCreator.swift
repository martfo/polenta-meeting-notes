// Vault creation at first run: the folder tree, the default summary prompt,
// and config.json with the defaults. Choosing an existing vault opens it
// without overwriting anything.

import Foundation

public enum VaultCreator {
    public static let folderNames = ["meetings", "speakers", "lancedb", "logs", "settings"]

    public static func configPath(for root: URL) -> URL {
        root.appendingPathComponent("settings/config.json")
    }

    public static func summaryPromptPath(for root: URL) -> URL {
        root.appendingPathComponent("settings/summary_prompt.md")
    }

    /// True when the location already holds a vault (its config exists).
    public static func isExistingVault(at root: URL) -> Bool {
        FileManager.default.fileExists(atPath: configPath(for: root).path)
    }

    /// Mirrors the backend's config schema and defaults.
    public static func defaultConfigJSON(vaultPath: String) -> String {
        let escaped = vaultPath
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return """
        {
          "vault_path": "\(escaped)",
          "backend_port": 8765,
          "lmstudio_base_url": "http://127.0.0.1:1234/v1",
          "embedding_model": "bge-m3",
          "language": "en",
          "match_threshold": 0.75,
          "veto_margin": 0.1,
          "audio_retention_days": 30,
          "ocr_enabled": true,
          "log_level": "info"
        }
        """
    }

    /// Creates the vault when the location is fresh; opens it untouched when
    /// it already is one. Returns true when a new vault was created.
    @discardableResult
    public static func createOrOpen(at root: URL, defaultSummaryPrompt: String?) throws -> Bool {
        let fileManager = FileManager.default
        if isExistingVault(at: root) {
            return false
        }
        for name in folderNames {
            try fileManager.createDirectory(
                at: root.appendingPathComponent(name), withIntermediateDirectories: true)
        }
        let promptPath = summaryPromptPath(for: root)
        if let defaultSummaryPrompt, !fileManager.fileExists(atPath: promptPath.path) {
            try defaultSummaryPrompt.write(to: promptPath, atomically: true, encoding: .utf8)
        }
        try defaultConfigJSON(vaultPath: root.path)
            .write(to: configPath(for: root), atomically: true, encoding: .utf8)
        return true
    }
}
