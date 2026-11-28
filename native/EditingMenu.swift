import AppKit

/// Route standard editing shortcuts through the focused native text responder.
@MainActor func installEditingMenu() {
    let main = NSApp.mainMenu ?? NSMenu()
    if main.items.isEmpty {
        let application = NSMenuItem()
        application.submenu = NSMenu(title: "Prompt Aid")
        main.addItem(application)
    }
    let edit = NSMenu(title: "Edit")
    func item(_ title: String, _ action: String, _ key: String, shift: Bool = false) {
        let entry = NSMenuItem(title: title, action: Selector(action), keyEquivalent: key)
        entry.keyEquivalentModifierMask = shift ? [.command, .shift] : [.command]
        // A nil target uses the responder chain, including SwiftUI's field editor.
        entry.target = nil
        edit.addItem(entry)
    }
    item("Undo", "undo:", "z")
    item("Redo", "redo:", "z", shift: true)
    edit.addItem(.separator())
    item("Cut", "cut:", "x")
    item("Copy", "copy:", "c")
    item("Paste", "paste:", "v")
    item("Select All", "selectAll:", "a")
    let menu = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
    menu.submenu = edit
    main.addItem(menu)
    NSApp.mainMenu = main
}
