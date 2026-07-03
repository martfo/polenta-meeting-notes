// The chosen microphone is remembered across launches. The store is injected
// so tests use an in-memory one; the app passes UserDefaults.

import Foundation

public protocol KeyValueStore {
    func string(forKey key: String) -> String?
    func set(_ value: String?, forKey key: String)
}

extension UserDefaults: KeyValueStore {
    public func set(_ value: String?, forKey key: String) {
        if let value { set(value as Any, forKey: key) } else { removeObject(forKey: key) }
    }
}

public struct MicrophonePreference {
    static let key = "selectedMicrophoneUID"
    private let store: KeyValueStore

    public init(store: KeyValueStore) {
        self.store = store
    }

    public func save(deviceUID: String) {
        store.set(deviceUID, forKey: Self.key)
    }

    public func restore() -> String? {
        store.string(forKey: Self.key)
    }
}
