"""The right-side trays (Properties, Browser) always have a way back:
their Window-menu entries work, and folding the sidebar brings back every
tray that was open — not just the tab in front (Marco, 0.5.1 Flatpak: the
menu entries greyed out)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QToolBar

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway INI for every QSettings() the windows open — the name
    imported into views.main_window included, or the MainWindow reads
    (and, on close, WRITES) the layout of whatever test ran before."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def test_the_window_menu_can_bring_back_every_tray(settings_file):
    from views.main_window import MainWindow
    win = MainWindow()
    for dock in win._sidebar_docks():
        assert dock.toggleViewAction().isEnabled(), dock.objectName()
    win.project_browser.hide()
    assert not win.project_browser.toggleViewAction().isChecked()
    win.project_browser.toggleViewAction().trigger()
    assert not win.project_browser.isHidden()


def test_unfolding_the_sidebar_brings_back_the_tabs_behind(settings_file,
                                                         monkeypatch):
    from PySide6.QtWidgets import QDockWidget
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    for _ in range(5):
        _app.processEvents()
    # On a real screen a tray tabbed behind another is not visible; the
    # offscreen platform shows them all, so play the real screen here.
    front = win.tray
    real = QDockWidget.isVisible
    monkeypatch.setattr(QDockWidget, "isVisible",
                        lambda d: real(d) and d is front)
    right = [d for d in win._sidebar_docks() if not d.isHidden()
             and win.dockWidgetArea(d) != Qt.LeftDockWidgetArea]
    win._set_sidebar_visible(False)
    win._set_sidebar_visible(True)
    for dock in right:
        assert not dock.isHidden(), dock.objectName()


def _shown(win):
    """The Window-menu checks follow the trays once the window is up."""
    win.show()
    for _ in range(5):
        _app.processEvents()
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_first_run_opens_the_everyday_trays_and_keeps_the_rest_ready(
        settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    assert not win.tray.isHidden()                    # Properties
    assert not win.project_browser.isHidden()          # the model's tree
    assert win.project_browser in win.tabifiedDockWidgets(win.tray)
    assert _tab_order(win)[:2] == ["Properties", "Browser"]
    _close(win)


def _tab_order(win):
    """The tabs of the group holding Properties, left to right."""
    from PySide6.QtCore import QPoint
    for tb in win._dock_tab_bars():
        texts = [tb.tabText(i) for i in range(tb.count())]
        if ("Properties" in texts and tb.isVisible()
                and win.rect().contains(tb.mapTo(win, QPoint(0, 0)))):
            return texts
    return []


def test_restore_default_panels_puts_everything_back(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    win.restore_default_trays()
    for _ in range(5):
        _app.processEvents()
    assert all(win.dockWidgetArea(d) == Qt.RightDockWidgetArea
               for d in win._sidebar_docks())
    assert not win.tray.isHidden() and not win.project_browser.isHidden()
    assert _tab_order(win)[:2] == ["Properties", "Browser"]
    # The test's own INI: the QSettings name imported above is not the
    # patched one, and the shared store keeps what earlier tests wrote.
    assert not QSettings(str(settings_file), QSettings.IniFormat).contains(
        "ui/hidden_trays")
    _close(win)


def test_every_tray_opens_at_start_up_unless_the_menu_closed_it(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.tray.hide()                     # lost by a fold, not by the menu
    win.project_browser.toggleViewAction().trigger()  # closed from the menu
    assert win.project_browser.isHidden()
    _close(win)                         # the layout is saved on close

    win = _shown(MainWindow())
    assert not win.tray.isHidden()
    assert win.project_browser.isHidden()
    win.project_browser.toggleViewAction().trigger()  # back from the menu
    _close(win)

    win = _shown(MainWindow())
    assert not any(d.isHidden() for d in (win.tray, win.project_browser))
    _close(win)


def test_a_folded_sidebar_opens_unfolded(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    open_ = {d.objectName() for d in win._sidebar_docks()
             if not d.isHidden()}
    win._set_sidebar_visible(False)
    _close(win)
    win = _shown(MainWindow())
    assert open_ and all(not d.isHidden() for d in win._sidebar_docks()
                         if d.objectName() in open_)
    _close(win)


def test_ai_opens_and_an_extension_may_ask_to_start_hidden(
        settings_file):
    from PySide6.QtWidgets import QLabel
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    dock = win.extension_panels().get("extension_ai")
    if dock is not None:                              # bundled, if loaded
        assert not dock.isHidden()
    app = ExtensionApp(win, "quiet")
    quiet = app.add_panel("Quiet", QLabel("q"), start_hidden=True)
    loud = ExtensionApp(win, "loud").add_panel("Loud", QLabel("l"))
    assert quiet.isHidden() and not loud.isHidden()
    win.set_tray_shown(quiet, True)                   # the user opens it…
    _close(win)
    win = _shown(MainWindow())                        # …and it stays open
    quiet = ExtensionApp(win, "quiet").add_panel("Quiet", QLabel("q"),
                                                 start_hidden=True)
    assert not quiet.isHidden()
    _close(win)


def test_a_new_extension_asking_to_start_hidden_does_so_on_a_used_profile(
        settings_file):
    from PySide6.QtWidgets import QLabel
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.project_browser.toggleViewAction().trigger()  # a choice is saved
    _close(win)
    win = _shown(MainWindow())
    late = ExtensionApp(win, "late").add_panel("Late", QLabel("l"),
                                               start_hidden=True)
    assert late.isHidden()                            # installed later: hidden
    assert win.project_browser.isHidden()             # the choice still rules
    _close(win)
