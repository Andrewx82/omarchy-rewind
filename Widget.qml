import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "omarchy-rewind"
  ipcTarget: "omarchy.rewind"
  manageIpc: false

  property bool enabledState: true
  property bool countdownEnabled: true
  property int countdownSeconds: 15
  property bool hasActiveUndo: false
  property string lastTitle: ""
  property int remainingSec: 0
  property int count: 0
  property bool bindingsInstalled: true
  property bool pauseMedia: true
  readonly property string version: "1.2.1"

  readonly property string rewindBin: decodeURIComponent(Qt.resolvedUrl("rewind").toString().replace(/^file:\/\//, ""))

  Process {
    id: ensureBinProc
    command: ["/bin/sh", "-c", "mkdir -p \"$HOME/.local/bin\" && ln -sf \"" + root.rewindBin + "\" \"$HOME/.local/bin/rewind\" && ln -sf \"" + root.rewindBin + "\" \"$HOME/.local/bin/omarchy-rewind\""]
  }

  function refresh() {
    if (!statusProc.running) {
      statusProc.running = true
    }
  }

  function broadcast(method) {
    var items = bar && typeof bar.moduleWidgets === "function"
      ? bar.moduleWidgets(moduleName) : [root]
    for (var i = 0; i < items.length; i++) {
      if (items[i] && typeof items[i][method] === "function") items[i][method]()
    }
  }

  Component.onCompleted: {
    ensureBinProc.running = true
    root.refresh()
  }

  IpcHandler {
    target: "omarchy.rewind"

    function refresh(): void {
      root.broadcast("refresh")
    }

    function toggle(): void {
      root.toggle()
    }

    function toggleMenu(): void {
      root.toggle()
    }

    function open(): void {
      root.open()
    }

    function close(): void {
      root.close()
    }
  }

  Process {
    id: statusProc
    command: [root.rewindBin, "--status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          root.enabledState = data.enabled !== false
          root.countdownEnabled = data.countdown_enabled !== false
          root.countdownSeconds = data.countdown_seconds || 15
          root.count = data.count || 0
          root.hasActiveUndo = root.count > 0
          root.bindingsInstalled = data.bindings_installed !== false
          root.pauseMedia = data.pause_media !== false
          if (data.last) {
            root.lastTitle = data.last.title || data.last.class || "App"
            root.remainingSec = data.last.remaining !== undefined ? data.last.remaining : 15
          } else {
            root.lastTitle = ""
            root.remainingSec = 0
          }
        } catch (e) {}
      }
    }
  }

  // 1-second countdown tick for active undo in timer mode
  Timer {
    id: countdownTimer
    interval: 1000
    repeat: true
    running: root.hasActiveUndo && root.countdownEnabled && root.remainingSec > 0
    onTriggered: {
      if (root.remainingSec > 1) {
        root.remainingSec -= 1
      } else {
        root.refresh()
      }
    }
  }

  // Passive fallback check; real-time updates are driven via IPC
  Timer {
    interval: 30000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  visible: root.hasActiveUndo || !root.setting("hideWhenIdle", false)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    fontSize: Style.bar.iconFont
    slotSize: root.hasActiveUndo && !vertical ? Style.bar.iconSlot * 2.5 : Style.bar.iconSlot
    active: root.hasActiveUndo || root.opened
    dimmed: !root.hasActiveUndo && !root.opened
    opacity: !root.enabledState ? 0.45 : 1.0

    text: {
      if (root.hasActiveUndo) {
        if (root.countdownEnabled && root.remainingSec >= 0) {
          return "󰁯 " + root.remainingSec + "s"
        } else {
          return "󰁯 Saved"
        }
      }
      return "󰁯"
    }

    tooltipText: {
      if (root.hasActiveUndo) {
        if (root.countdownEnabled && root.remainingSec >= 0) {
          return "Rewind (" + root.remainingSec + "s remaining: " + root.lastTitle + ")\nClick for menu or Super+U to restore"
        } else {
          return "Rewind (Saved in memory: " + root.lastTitle + ")\nClick for menu or Super+U to restore"
        }
      }
      if (root.enabledState) {
        return "Rewind: ON" + (root.countdownEnabled ? " (" + root.countdownSeconds + "s timer)" : " (Manual mode)") + "\nClick for settings"
      }
      return "Rewind: OFF\nClick for settings"
    }

    onPressed: function(b) {
      root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(settingsColumn.implicitHeight)

    Column {
      id: settingsColumn
      width: parent.width
      spacing: Style.space(12)

      // Header
      Item {
        width: parent.width
        height: Style.space(28)
        implicitHeight: height

        Row {
          anchors.fill: parent
          spacing: Style.space(10)

          Text {
            text: "󰁯"
            color: root.barForeground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            text: "Rewind Settings"
            color: root.barForeground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
            anchors.verticalCenter: parent.verticalCenter
          }
        }
      }

      // Shortcuts setup banner (shown if Hyprland bindings not yet added)
      BorderSurface {
        width: parent.width
        height: Style.space(72)
        implicitHeight: visible ? height : 0
        visible: !root.bindingsInstalled
        radius: Style.cornerRadius
        color: Style.normalFillFor(root.barForeground, Color.urgent)
        borderSpec: Border.controlSpec("normal", root.barForeground, Color.urgent)

        Row {
          anchors.fill: parent
          anchors.margins: Style.space(8)
          spacing: Style.space(8)

          Text {
            text: "󰀦"
            color: Color.urgent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            width: parent.width - Style.space(110)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Shortcuts Not Enabled"
              textFormat: Text.PlainText
              color: root.barForeground
              font.bold: true
              font.pixelSize: Style.font.caption
            }
            Text {
              text: "Enable Super+W & Super+U"
              textFormat: Text.PlainText
              color: root.barForeground
              opacity: 0.8
              font.pixelSize: Style.font.caption
            }
          }

          Button {
            width: Style.space(74)
            height: Style.space(32)
            text: "Enable"
            bordered: true
            accent: Color.urgent
            anchors.verticalCenter: parent.verticalCenter
            onClicked: {
              if (root.bar) root.bar.run(root.rewindBin + " setup")
            }
          }
        }
      }

      // Shortcuts active banner (shown if Hyprland bindings are active)
      BorderSurface {
        width: parent.width
        height: Style.space(56)
        implicitHeight: visible ? height : 0
        visible: root.bindingsInstalled
        radius: Style.cornerRadius
        color: Style.controlFill("normal", root.barForeground)
        borderSpec: Border.controlSpec("normal", root.barForeground)

        Row {
          anchors.left: parent.left
          anchors.leftMargin: Style.space(10)
          anchors.right: restoreBtn.left
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(8)

          Text {
            text: "󰌌"
            color: Color.accent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(1)

            Text {
              text: "Shortcuts Active"
              textFormat: Text.PlainText
              color: root.barForeground
              font.bold: true
              font.pixelSize: Style.font.caption
            }
            Text {
              text: "Super+W & Super+U"
              textFormat: Text.PlainText
              color: root.barForeground
              opacity: 0.75
              font.pixelSize: Style.font.caption
            }
          }
        }

        Button {
          id: restoreBtn
          width: Style.space(175)
          height: Style.space(34)
          fontSize: Style.font.bodySmall
          horizontalPadding: Style.space(8)
          text: "Restore Defaults"
          bordered: true
          anchors.right: parent.right
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          onClicked: {
            if (root.bar) root.bar.run(root.rewindBin + " remove-bindings")
          }
        }
      }

      // Feature Toggle
      Toggle {
        width: parent.width
        label: "Enable Rewind"
        description: "Intercept Super+W with undo grace"
        checked: root.enabledState
        onClicked: {
          if (root.bar) root.bar.run(root.rewindBin + " toggle")
        }
      }

      // Countdown Timer Toggle
      Toggle {
        width: parent.width
        label: "Countdown Timer"
        description: root.countdownEnabled ? "Auto-close after countdown" : "Saved in memory until restored/replaced"
        checked: root.countdownEnabled
        onClicked: {
          if (root.bar) root.bar.run(root.rewindBin + " config --toggle-countdown")
        }
      }

      // Duration selector (when countdown timer is enabled)
      Item {
        width: parent.width
        height: Style.space(66)
        implicitHeight: visible ? height : 0
        visible: root.countdownEnabled

        Column {
          anchors.fill: parent
          spacing: Style.space(8)

          Row {
            spacing: Style.space(6)

            Text {
              text: "Countdown Duration:"
              color: root.barForeground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
              opacity: 0.8
            }

            Text {
              text: root.countdownSeconds + " seconds"
              color: Color.accent
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }

          Row {
            spacing: Style.space(6)
            width: parent.width

            Repeater {
              model: [5, 10, 15, 30, 60]
              delegate: Button {
                width: Style.space(54)
                height: Style.space(32)
                text: modelData + "s"
                bordered: true
                selected: root.countdownSeconds === modelData
                onClicked: {
                  if (root.bar) root.bar.run(root.rewindBin + " config --duration " + modelData)
                }
              }
            }
          }
        }
      }

      // Manual Mode info banner (when countdown is disabled)
      BorderSurface {
        width: parent.width
        height: Style.space(68)
        implicitHeight: visible ? height : 0
        visible: !root.countdownEnabled
        radius: Style.cornerRadius
        color: Style.normalFillFor(root.barForeground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.barForeground, Color.accent)

        Row {
          anchors.fill: parent
          anchors.margins: Style.space(8)
          spacing: Style.space(8)

          Text {
            text: "󰋽"
            color: Color.accent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            width: parent.width - Style.space(36)
            text: "Manual Mode: Closed window stays saved in memory until you press Super+U or close another window (which closes the previous and replaces it)."
            color: root.barForeground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
            anchors.verticalCenter: parent.verticalCenter
          }
        }
      }

      // Auto-Pause Media Toggle
      Toggle {
        width: parent.width
        label: "Auto-Pause Media"
        description: "Pause video/audio on close & resume on rewind"
        checked: root.pauseMedia
        onClicked: {
          if (root.bar) root.bar.run(root.rewindBin + " config --toggle-media")
        }
      }

      // If there is currently an app in hidden memory / undo queue
      Item {
        width: parent.width
        height: Style.space(76)
        implicitHeight: visible ? height : 0
        visible: root.hasActiveUndo

        Column {
          anchors.fill: parent
          spacing: Style.space(8)

          PanelSeparator { width: parent.width }

          Text {
            text: "Currently Saved: " + root.lastTitle + (root.countdownEnabled && root.remainingSec > 0 ? " (" + root.remainingSec + "s)" : "")
            textFormat: Text.PlainText
            color: Color.accent
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }

          Row {
            spacing: Style.space(8)
            width: parent.width

            Button {
              width: Style.space(140)
              height: Style.space(34)
              text: "Rewind Window"
              iconText: "󰁪"
              bordered: true
              accent: Color.accent
              onClicked: {
                root.close()
                if (root.bar) root.bar.run(root.rewindBin + " restore")
              }
            }

            Button {
              width: Style.space(140)
              height: Style.space(34)
              text: "Close Permanently"
              iconText: "󰅖"
              bordered: true
              onClicked: {
                root.close()
                if (root.bar) root.bar.run(root.rewindBin + " clear")
              }
            }
          }
        }
      }

      // Footer with version
      Item {
        width: parent.width
        height: Style.space(20)
        implicitHeight: height

        Text {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: "v" + root.version
          textFormat: Text.PlainText
          color: root.barForeground
          opacity: 0.75
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
