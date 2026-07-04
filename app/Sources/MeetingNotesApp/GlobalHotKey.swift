// A system-wide hotkey to start and stop recording, so it works even when
// another app (the call you are in) has focus. Uses Carbon's
// RegisterEventHotKey, the standard mechanism for background hotkeys, which
// needs no Accessibility permission. The combination is configurable; a
// registration can fail if another app already owns the combination, and that
// is reported so the user can pick another.

import AppKit
import Carbon

struct ShortcutModifiers: OptionSet {
    let rawValue: Int
    static let command = ShortcutModifiers(rawValue: 1 << 0)
    static let option = ShortcutModifiers(rawValue: 1 << 1)
    static let control = ShortcutModifiers(rawValue: 1 << 2)
    static let shift = ShortcutModifiers(rawValue: 1 << 3)

    /// Carbon modifier mask for RegisterEventHotKey.
    var carbon: UInt32 {
        var mask: UInt32 = 0
        if contains(.command) { mask |= UInt32(cmdKey) }
        if contains(.option) { mask |= UInt32(optionKey) }
        if contains(.control) { mask |= UInt32(controlKey) }
        if contains(.shift) { mask |= UInt32(shiftKey) }
        return mask
    }

    /// The combination as menu symbols, in the conventional order.
    var display: String {
        var text = ""
        if contains(.control) { text += "\u{2303}" }
        if contains(.option) { text += "\u{2325}" }
        if contains(.shift) { text += "\u{21E7}" }
        if contains(.command) { text += "\u{2318}" }
        return text
    }
}

enum RecordShortcut {
    static let key = "recordShortcutKey"
    static let modifiersKey = "recordShortcutModifiers"
    static let defaultKey = "r"
    static let defaultModifiers: ShortcutModifiers = [.control, .option, .command]

    static func displayString() -> String {
        let defaults = UserDefaults.standard
        let key = (defaults.string(forKey: Self.key) ?? defaultKey).uppercased()
        let raw = defaults.object(forKey: modifiersKey) as? Int ?? defaultModifiers.rawValue
        return ShortcutModifiers(rawValue: raw).display + key
    }
}

/// ANSI virtual key codes for the letters and digits a shortcut may use.
private let ansiKeyCodes: [Character: UInt32] = [
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19,
    "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
]

final class GlobalHotKey {
    static let shared = GlobalHotKey()

    /// Run when the hotkey fires. Set once at launch.
    var action: (() -> Void)?

    private var hotKeyRef: EventHotKeyRef?
    private var handlerInstalled = false

    private init() {}

    /// Register the combination stored in user defaults. Returns whether it
    /// registered; false usually means another app already owns it.
    @discardableResult
    func applyFromDefaults() -> Bool {
        let defaults = UserDefaults.standard
        let keyString = defaults.string(forKey: RecordShortcut.key) ?? RecordShortcut.defaultKey
        let raw = defaults.object(forKey: RecordShortcut.modifiersKey) as? Int
            ?? RecordShortcut.defaultModifiers.rawValue
        guard let character = keyString.lowercased().first,
              let keyCode = ansiKeyCodes[character] else {
            unregister()
            return false
        }
        let modifiers = ShortcutModifiers(rawValue: raw)
        // A hotkey with no modifier would swallow a plain keypress everywhere.
        guard !modifiers.isEmpty else {
            unregister()
            return false
        }
        return register(keyCode: keyCode, modifiers: modifiers.carbon)
    }

    private func register(keyCode: UInt32, modifiers: UInt32) -> Bool {
        unregister()
        installHandlerIfNeeded()
        var ref: EventHotKeyRef?
        let id = EventHotKeyID(signature: OSType(0x504D_4E54), id: 1)  // 'PMNT'
        let status = RegisterEventHotKey(
            keyCode, modifiers, id, GetEventDispatcherTarget(), 0, &ref)
        if status == noErr {
            hotKeyRef = ref
            return true
        }
        return false
    }

    func unregister() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
            self.hotKeyRef = nil
        }
    }

    private func installHandlerIfNeeded() {
        guard !handlerInstalled else { return }
        handlerInstalled = true
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard), eventKind: OSType(kEventHotKeyPressed))
        InstallEventHandler(
            GetEventDispatcherTarget(),
            { _, _, _ in
                DispatchQueue.main.async { GlobalHotKey.shared.action?() }
                return noErr
            },
            1, &eventType, nil, nil)
    }
}
