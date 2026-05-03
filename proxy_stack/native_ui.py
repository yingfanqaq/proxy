"""Native flow editor UI using PySide6 / Qt — Modern dark theme inspired by Prototype."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTextCursor, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .config import load_config, save_config
from .flows import normalized_flows
from .manager import restart_all, start_all, status, stop_all

BG_MAIN = QColor("#0a0a0a")
BG_SIDEBAR = QColor("#121212")
BG_CARD = QColor("#1a1a1a")
BORDER_MAIN = QColor(255, 255, 255, 26)
TEXT_PRIMARY = QColor("#f3f4f6")
TEXT_SECONDARY = QColor("#9ca3af")
ACCENT = QColor("#2e66ff")
GRID_DOT_COLOR = QColor(255, 255, 255, 13)
GRID_STEP = 20

NODE_W = 240
NODE_H = 118
EDGE_WIDTH = 2
PORT_R = 6

NODE_COLORS: dict[str, QColor] = {
    "input": QColor("#3b82f6"),
    "transform": QColor("#a855f7"),
    "output": QColor("#10b981"),
}

VALID_CONNECTIONS = {("input", "transform"), ("transform", "output")}
LOCAL_PROVIDER_PORTS = {
    "codex": 39121,
    "gemini": 39122,
    "claude": 39123,
}
PROVIDER_PROTOCOLS = {
    "codex": "Custom",
    "claude": "Anthropic",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "custom": "Custom",
}
FORMAT_PROTOCOLS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
}

COMPONENT_SECTIONS = [
    (
        "Input Nodes",
        [
            {"kind": "input", "label": "Codex Proxy", "meta": {"provider": "codex", "subtype": "proxy", "protocol": "Custom"}},
            {"kind": "input", "label": "Claude Proxy", "meta": {"provider": "claude", "subtype": "proxy", "protocol": "Anthropic"}},
            {"kind": "input", "label": "Gemini Proxy", "meta": {"provider": "gemini", "subtype": "proxy", "protocol": "Gemini"}},
            {"kind": "input", "label": "OpenAI API", "meta": {"provider": "openai", "subtype": "api", "protocol": "OpenAI", "base_url": "https://api.openai.com/v1"}},
            {"kind": "input", "label": "Claude API", "meta": {"provider": "anthropic", "subtype": "api", "protocol": "Anthropic", "base_url": "https://api.anthropic.com"}},
            {"kind": "input", "label": "Custom API", "meta": {"provider": "custom", "subtype": "api", "protocol": "Custom", "base_url": ""}},
        ],
    ),
    (
        "Transform Nodes",
        [
            {"kind": "transform", "label": "LiteLLM Transform", "meta": {"engine": "litellm"}},
        ],
    ),
    (
        "Output Nodes",
        [
            {"kind": "output", "label": "OpenAI Output", "meta": {"format": "openai", "protocol": "OpenAI", "port": 4001}},
            {"kind": "output", "label": "Anthropic Output", "meta": {"format": "anthropic", "protocol": "Anthropic", "port": 4000}},
            {"kind": "output", "label": "Gemini Output", "meta": {"format": "gemini", "protocol": "Gemini", "port": 4002}},
        ],
    ),
]


def _button_style(primary: bool = False) -> str:
    if primary:
        return (
            "QPushButton {"
            " background: #2e66ff; color: white; border: none; border-radius: 10px;"
            " padding: 0 14px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: #3a72ff; }"
            "QPushButton:pressed { background: #2558e5; }"
            "QPushButton:disabled { background: #3556a3; color: #d1d5db; }"
        )
    return (
        "QPushButton {"
        " background: rgba(255,255,255,0.05); color: #f3f4f6;"
        " border: 1px solid rgba(255,255,255,0.1); border-radius: 10px;"
        " padding: 0 12px; font-size: 12px; font-weight: 600; }"
        "QPushButton:hover { background: rgba(255,255,255,0.08); }"
        "QPushButton:pressed { background: rgba(255,255,255,0.12); }"
    )


def _input_style() -> str:
    return (
        "QLineEdit {"
        " background: #0f0f0f; color: #f3f4f6;"
        " border: 1px solid rgba(255,255,255,0.1); border-radius: 10px;"
        " padding: 8px 10px; font-size: 12px; }"
        "QLineEdit:focus { border-color: #2e66ff; }"
    )


def _card_style() -> str:
    return (
        "background: #1a1a1a;"
        "border: 1px solid rgba(255,255,255,0.1);"
        "border-radius: 14px;"
    )


def _panel_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #9ca3af; font-size: 10px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;")
    return label


def _service_name_for_provider(provider: str) -> str | None:
    if provider in {"codex", "gemini", "claude"}:
        return provider
    return None


class Port(QGraphicsEllipseItem):
    def __init__(self, is_output: bool, parent: "FlowNode"):
        super().__init__(-PORT_R, -PORT_R, PORT_R * 2, PORT_R * 2, parent)
        self.is_output = is_output
        self.node: FlowNode = parent
        self.edges: list[Edge] = []
        self.setBrush(QBrush(NODE_COLORS.get(parent.kind, TEXT_SECONDARY)))
        self.setPen(QPen(BG_CARD, 3))
        self.setZValue(3)
        self.setAcceptHoverEvents(True)

    def center_scene(self) -> QPointF:
        return self.scenePos()

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(ACCENT))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(NODE_COLORS.get(self.node.kind, TEXT_SECONDARY)))
        super().hoverLeaveEvent(event)


class Edge(QGraphicsPathItem):
    def __init__(self, source_port: Port, dest_port: Port | None = None):
        super().__init__()
        self.source_port = source_port
        self.dest_port = dest_port
        pen = QPen(ACCENT, EDGE_WIDTH, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        source_port.edges.append(self)
        if dest_port:
            dest_port.edges.append(self)

    def update_path(self, end_point: QPointF | None = None):
        p1 = self.source_port.center_scene()
        p2 = end_point or (self.dest_port.center_scene() if self.dest_port else p1)
        dx = max(abs(p2.x() - p1.x()) * 0.5, 60)
        path = QPainterPath(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def remove(self):
        if self in self.source_port.edges:
            self.source_port.edges.remove(self)
        if self.dest_port and self in self.dest_port.edges:
            self.dest_port.edges.remove(self)
        if self.scene():
            self.scene().removeItem(self)


class FlowNode(QGraphicsRectItem):
    def __init__(self, kind: str, label: str, node_id: str = "", meta: dict[str, Any] | None = None):
        super().__init__(0, 0, NODE_W, NODE_H)
        self.kind = kind
        self.label = label
        self.node_id = node_id or uuid.uuid4().hex[:8]
        self.meta = dict(meta or {})
        self.status = str(self.meta.get("status", "offline"))
        self._color = NODE_COLORS.get(kind, TEXT_SECONDARY)

        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(1)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        self.input_port: Port | None = None
        self.output_port: Port | None = None
        if kind != "input":
            self.input_port = Port(False, self)
            self.input_port.setPos(0, NODE_H / 2)
        if kind != "output":
            self.output_port = Port(True, self)
            self.output_port.setPos(NODE_W, NODE_H / 2)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, NODE_W, NODE_H)

        border_color = ACCENT if self.isSelected() else BORDER_MAIN
        painter.setPen(QPen(border_color, 2 if self.isSelected() else 1))
        painter.setBrush(QBrush(BG_CARD))
        painter.drawRoundedRect(rect, 12, 12)

        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(0, 0, NODE_W, 40), 12, 12)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 20, NODE_W, 20))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 8)))
        painter.drawPath(header_path - clip)

        painter.setBrush(QBrush(self._color.darker(115)))
        painter.setPen(QPen(self._color, 2))
        painter.drawEllipse(QPointF(20, 20), 12, 12)

        painter.setPen(QPen(self._color))
        painter.setFont(QFont("SF Pro Display", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(8, 8, 24, 24), Qt.AlignmentFlag.AlignCenter, self.kind[0].upper())

        painter.setPen(QPen(TEXT_PRIMARY))
        painter.setFont(QFont("SF Pro Display", 13, QFont.Weight.Bold))
        painter.drawText(QRectF(44, 9, NODE_W - 70, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label[:22])

        if self.kind == "input":
            status_color = QColor("#10b981") if self.status == "online" else QColor("#ef4444")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(status_color))
            painter.drawEllipse(QPointF(NODE_W - 16, 20), 4, 4)

        painter.setFont(QFont("SF Pro Display", 10))
        painter.setPen(QPen(TEXT_SECONDARY))
        y = 56

        if self.kind == "input":
            painter.drawText(QRectF(18, y, 72, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Protocol:")
            painter.setPen(QPen(self._color))
            painter.setFont(QFont("SF Mono", 10, QFont.Weight.Bold))
            painter.drawText(QRectF(92, y, NODE_W - 110, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(self.meta.get("protocol", "Custom")))
            painter.setPen(QPen(TEXT_SECONDARY))
            painter.setFont(QFont("SF Pro Display", 10))
            y += 24
            if self.meta.get("subtype") == "proxy":
                painter.drawText(QRectF(18, y, 72, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Port:")
                painter.setPen(QPen(TEXT_PRIMARY))
                painter.setFont(QFont("SF Mono", 10, QFont.Weight.Bold))
                painter.drawText(QRectF(92, y, NODE_W - 110, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(self.meta.get("port", "---")))
            else:
                painter.drawText(QRectF(18, y, NODE_W - 36, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(self.meta.get("base_url") or "External API endpoint"))

        elif self.kind == "transform":
            painter.drawText(QRectF(18, y, 72, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Engine:")
            painter.setPen(QPen(self._color))
            painter.setFont(QFont("SF Mono", 10, QFont.Weight.Bold))
            painter.drawText(QRectF(92, y, NODE_W - 110, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "LiteLLM")

        else:
            painter.drawText(QRectF(18, y, 72, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Listen:")
            painter.setPen(QPen(self._color))
            painter.setFont(QFont("SF Mono", 10, QFont.Weight.Bold))
            painter.drawText(QRectF(92, y, NODE_W - 110, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"127.0.0.1:{self.meta.get('port', 4000)}")
            painter.setPen(QPen(TEXT_SECONDARY))
            painter.setFont(QFont("SF Pro Display", 10))
            y += 24
            painter.drawText(QRectF(18, y, 72, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Format:")
            painter.setPen(QPen(TEXT_PRIMARY))
            painter.setFont(QFont("SF Mono", 10))
            painter.drawText(QRectF(92, y, NODE_W - 110, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(self.meta.get("protocol", "Anthropic")))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in (self.input_port, self.output_port):
                if port:
                    for edge in port.edges:
                        edge.update_path()
        return super().itemChange(change, value)

    def update_meta(self, **changes: Any):
        self.meta.update(changes)
        if "status" in changes:
            self.status = str(changes["status"])
        self.update()


class FlowScene(QGraphicsScene):
    flow_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, 4000, 3000)
        self._temp_edge: Edge | None = None
        self._drag_source_port: Port | None = None

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, BG_MAIN)
        painter.setPen(QPen(GRID_DOT_COLOR, 2))
        left = int(rect.left()) - (int(rect.left()) % GRID_STEP)
        top = int(rect.top()) - (int(rect.top()) % GRID_STEP)
        points: list[QPointF] = []
        for x in range(left, int(rect.right()), GRID_STEP):
            for y in range(top, int(rect.bottom()), GRID_STEP):
                points.append(QPointF(x, y))
        if points:
            painter.drawPoints(points)

    def add_node(self, kind: str, label: str, pos: QPointF, meta: dict[str, Any] | None = None) -> FlowNode:
        node = FlowNode(kind, label, meta=meta)
        self.addItem(node)
        node.setPos(pos)
        self.flow_changed.emit()
        return node

    def add_edge(self, source: Port, dest: Port) -> Edge | None:
        if (source.node.kind, dest.node.kind) not in VALID_CONNECTIONS:
            return None
        for edge in source.edges:
            if edge.dest_port is dest:
                return None
        edge = Edge(source, dest)
        self.addItem(edge)
        edge.update_path()
        self.flow_changed.emit()
        return edge

    def start_edge_drag(self, port: Port, scene_pos: QPointF):
        if not port.is_output:
            return
        self._drag_source_port = port
        self._temp_edge = Edge(port)
        self._temp_edge.setPen(QPen(ACCENT, EDGE_WIDTH, Qt.PenStyle.DashLine))
        self._temp_edge.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.addItem(self._temp_edge)
        self._temp_edge.update_path(scene_pos)

    def update_edge_drag(self, scene_pos: QPointF):
        if self._temp_edge:
            self._temp_edge.update_path(scene_pos)

    def finish_edge_drag(self, scene_pos: QPointF):
        if not self._temp_edge or not self._drag_source_port:
            self._cleanup_drag()
            return
        target_port: Port | None = None
        for item in self.items(scene_pos):
            if isinstance(item, Port) and not item.is_output and item.node is not self._drag_source_port.node:
                target_port = item
                break
        self._temp_edge.remove()
        if target_port:
            self.add_edge(self._drag_source_port, target_port)
        self._cleanup_drag()

    def _cleanup_drag(self):
        self._temp_edge = None
        self._drag_source_port = None

    def all_nodes(self) -> list[FlowNode]:
        return [item for item in self.items() if isinstance(item, FlowNode)]

    def all_edges(self) -> list[Edge]:
        return [item for item in self.items() if isinstance(item, Edge) and item.dest_port is not None]

    def delete_selected(self):
        for item in self.selectedItems():
            if isinstance(item, FlowNode):
                for port in (item.input_port, item.output_port):
                    if port:
                        for edge in list(port.edges):
                            edge.remove()
                self.removeItem(item)
            elif isinstance(item, Edge):
                item.remove()
        self.flow_changed.emit()


class FlowView(QGraphicsView):
    node_placed = Signal(QPointF)

    def __init__(self, scene: FlowScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: #0a0a0a;")
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dragging_edge = False
        self._placement_pending = False

    def set_placement_mode(self, active: bool):
        self._placement_pending = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, Port) and item.is_output:
                self._dragging_edge = True
                self.scene().start_edge_drag(item, self.mapToScene(event.pos()))
                return
            if self._placement_pending and item is None:
                self.node_placed.emit(self.mapToScene(event.pos()))
                return
        if event.button() == Qt.MouseButton.RightButton and self._placement_pending:
            self.set_placement_mode(False)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_edge:
            self.scene().update_edge_drag(self.mapToScene(event.pos()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_edge:
            self._dragging_edge = False
            self.scene().finish_edge_drag(self.mapToScene(event.pos()))
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._placement_pending:
            self.set_placement_mode(False)
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.scene().delete_selected()
            return
        super().keyPressEvent(event)


class Sidebar(QWidget):
    place_requested = Signal(str, str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(272)
        self.setStyleSheet("background: #121212; border-right: 1px solid rgba(255,255,255,0.1);")
        self._item_data: dict[int, dict[str, Any]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Components")
        title.setStyleSheet("color: #9ca3af; font-size: 12px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;")
        layout.addWidget(title)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search nodes...")
        self._search.setStyleSheet(_input_style())
        self._search.textChanged.connect(self._rebuild_list)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #121212; border: none; outline: none; color: #f3f4f6; }"
            "QListWidget::item { border: none; margin: 2px 0; padding: 0; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_click)
        layout.addWidget(self._list, 1)

        self._rebuild_list()

    def _rebuild_list(self):
        query = self._search.text().strip().lower()
        self._list.clear()
        self._item_data.clear()
        row = 0
        for section_title, items in COMPONENT_SECTIONS:
            filtered = [item for item in items if not query or query in item["label"].lower()]
            if not filtered:
                continue
            header = QListWidgetItem(section_title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setSizeHint(QSize(0, 28))
            header.setForeground(TEXT_SECONDARY)
            header.setFont(QFont("SF Pro Display", 10, QFont.Weight.Bold))
            self._list.addItem(header)
            row += 1
            for item in filtered:
                entry = QListWidgetItem(f"  {item['label']}")
                entry.setSizeHint(QSize(0, 42))
                entry.setForeground(TEXT_PRIMARY)
                entry.setFont(QFont("SF Pro Display", 12, QFont.Weight.Bold))
                self._list.addItem(entry)
                self._item_data[row] = item
                row += 1

    def _on_click(self, item: QListWidgetItem):
        data = self._item_data.get(self._list.row(item))
        if data:
            self.place_requested.emit(data["kind"], data["label"], dict(data.get("meta", {})))


class LogPanel(QWidget):
    message_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(220)
        self.setStyleSheet("background: #121212; border-top: 1px solid rgba(255,255,255,0.1);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Runtime Terminal")
        title.setStyleSheet("color: #f3f4f6; font-size: 11px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;")
        header.addWidget(title)
        header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(28)
        clear_btn.setStyleSheet(_button_style(False))
        clear_btn.clicked.connect(lambda: self._output.setText("[standby] Waiting for activity..."))
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit {"
            " background: #121212; color: #9ca3af; border: none;"
            " font-family: 'SF Mono'; font-size: 11px; }"
        )
        self._output.setText("[standby] Waiting for activity...")
        layout.addWidget(self._output, 1)
        self.message_ready.connect(self._append_message)

    def append(self, message: str):
        self.message_ready.emit(message)

    def _append_message(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._output.append(f"[{timestamp}] {message}")
        self._output.moveCursor(QTextCursor.MoveOperation.End)


class InspectorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.setStyleSheet("background: #121212; border-left: 1px solid rgba(255,255,255,0.1);")
        self._selected_node: FlowNode | None = None
        self._services: dict[str, dict[str, object]] = {}
        self._save_callback = None
        self._test_callback = None
        self._start_callback = None
        self._restart_callback = None
        self._stop_callback = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Node Configuration")
        title.setStyleSheet("color: #f3f4f6; font-size: 14px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedHeight(28)
        self._close_btn.setStyleSheet(_button_style(False))
        self._close_btn.clicked.connect(self.clear_selection)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._summary = QLabel("Select a node to inspect its configuration.")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #9ca3af; font-size: 12px; line-height: 1.5;")
        layout.addWidget(self._summary)

        meta_card = QFrame()
        meta_card.setStyleSheet(_card_style())
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.setContentsMargins(14, 14, 14, 14)
        meta_layout.setSpacing(8)
        meta_layout.addWidget(_panel_title("Metadata"))
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Node name")
        self._name_input.setStyleSheet(_input_style())
        self._name_input.editingFinished.connect(self._save_name)
        meta_layout.addWidget(self._name_input)
        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        meta_layout.addWidget(self._details_label)
        layout.addWidget(meta_card)

        params_card = QFrame()
        params_card.setStyleSheet(_card_style())
        params_layout = QVBoxLayout(params_card)
        params_layout.setContentsMargins(14, 14, 14, 14)
        params_layout.setSpacing(8)
        params_layout.addWidget(_panel_title("Parameters"))
        self._param_primary = QLabel("")
        self._param_primary.setStyleSheet("color: #f3f4f6; font-size: 12px; font-weight: 600;")
        self._param_secondary = QLabel("")
        self._param_secondary.setWordWrap(True)
        self._param_secondary.setStyleSheet("color: #9ca3af; font-size: 11px;")
        params_layout.addWidget(self._param_primary)
        params_layout.addWidget(self._param_secondary)
        self._test_btn = QPushButton("Test Link")
        self._test_btn.setFixedHeight(32)
        self._test_btn.setStyleSheet(_button_style(False))
        self._test_btn.clicked.connect(self._run_test)
        params_layout.addWidget(self._test_btn)
        layout.addWidget(params_card)

        services_card = QFrame()
        services_card.setStyleSheet(_card_style())
        services_layout = QVBoxLayout(services_card)
        services_layout.setContentsMargins(14, 14, 14, 14)
        services_layout.setSpacing(10)
        services_layout.addWidget(_panel_title("Services"))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._start_btn = QPushButton("Start")
        self._restart_btn = QPushButton("Restart")
        self._stop_btn = QPushButton("Stop")
        for btn in (self._start_btn, self._restart_btn, self._stop_btn):
            btn.setFixedHeight(30)
            btn.setStyleSheet(_button_style(False))
            buttons.addWidget(btn)
        self._start_btn.clicked.connect(lambda: self._start_callback and self._start_callback())
        self._restart_btn.clicked.connect(lambda: self._restart_callback and self._restart_callback())
        self._stop_btn.clicked.connect(lambda: self._stop_callback and self._stop_callback())
        services_layout.addLayout(buttons)
        self._service_status = QLabel("Checking services...")
        self._service_status.setWordWrap(True)
        self._service_status.setStyleSheet("color: #9ca3af; font-size: 11px;")
        services_layout.addWidget(self._service_status)
        layout.addWidget(services_card)
        layout.addStretch()

        self.clear_selection()

    def set_callbacks(self, save_callback, test_callback, start_callback, restart_callback, stop_callback):
        self._save_callback = save_callback
        self._test_callback = test_callback
        self._start_callback = start_callback
        self._restart_callback = restart_callback
        self._stop_callback = stop_callback

    def update_services(self, services: dict[str, dict[str, object]]):
        self._services = services
        if not services:
            self._service_status.setText("No services configured")
            return
        lines = []
        for name, info in sorted(services.items()):
            healthy = bool(info.get("healthy"))
            port = info.get("port")
            dot = "●"
            color = "#10b981" if healthy else "#ef4444"
            suffix = f" :{port}" if port else ""
            lines.append(f"<span style='color:{color}'>{dot}</span> <span style='color:#f3f4f6'>{name}{suffix}</span>")
        self._service_status.setText("<br>".join(lines))

    def show_node(self, node: FlowNode | None):
        self._selected_node = node
        if node is None:
            self._summary.setText("Select a node to inspect its configuration and service relationship.")
            self._name_input.clear()
            self._name_input.setEnabled(False)
            self._details_label.setText("No node selected")
            self._param_primary.setText("Telemetry idle")
            self._param_secondary.setText("Place or select a node on the canvas to view protocol, port, and health details.")
            self._test_btn.setEnabled(False)
            self._close_btn.setEnabled(False)
            return

        self._close_btn.setEnabled(True)
        self._name_input.setEnabled(True)
        self._name_input.setText(node.label)
        self._summary.setText(f"Editing {node.kind} node {node.node_id}.")
        self._details_label.setText(self._details_text(node))
        self._param_primary.setText(self._primary_text(node))
        self._param_secondary.setText(self._secondary_text(node))
        self._test_btn.setEnabled(node.kind == "input")

    def clear_selection(self):
        scene = self._selected_node.scene() if self._selected_node else None
        if scene:
            scene.clearSelection()
        self.show_node(None)

    def _details_text(self, node: FlowNode) -> str:
        if node.kind == "input":
            return f"Type: {node.meta.get('subtype', 'api')}\nProtocol: {node.meta.get('protocol', 'Custom')}"
        if node.kind == "transform":
            return f"Engine: {node.meta.get('engine', 'litellm')}"
        return f"Format: {node.meta.get('format', 'anthropic')}\nPort: {node.meta.get('port', 4000)}"

    def _primary_text(self, node: FlowNode) -> str:
        if node.kind == "input":
            return f"Status: {node.status}"
        if node.kind == "transform":
            return f"Engine: {node.meta.get('engine', 'litellm')}"
        return f"Endpoint: 127.0.0.1:{node.meta.get('port', 4000)}"

    def _secondary_text(self, node: FlowNode) -> str:
        if node.kind == "input":
            if node.meta.get("subtype") == "proxy":
                return f"Local provider on port {node.meta.get('port', '---')}."
            return str(node.meta.get("base_url") or "External API endpoint.")
        if node.kind == "transform":
            return "Routes upstream traffic through LiteLLM."
        return f"Exposes {node.meta.get('protocol', 'Anthropic')} output for client access."

    def _save_name(self):
        if not self._selected_node or not self._save_callback:
            return
        new_name = self._name_input.text().strip()
        if not new_name:
            self._name_input.setText(self._selected_node.label)
            return
        self._save_callback(self._selected_node, new_name)

    def _run_test(self):
        if self._selected_node and self._test_callback:
            self._test_callback(self._selected_node)


class MainWindow(QMainWindow):
    status_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 920)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet("QMainWindow { background: #0a0a0a; }")

        self._pending_kind: str | None = None
        self._pending_label: str | None = None
        self._pending_meta: dict[str, Any] = {}
        self._flow_models_by_id: dict[str, list[dict[str, Any]]] = {}

        self._scene = FlowScene(self)
        self._scene.selectionChanged.connect(self._sync_selection)

        self._view = FlowView(self._scene, self)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._view.node_placed.connect(self._on_node_placed)

        self._sidebar = Sidebar()
        self._sidebar.place_requested.connect(self._on_place_requested)

        self._inspector = InspectorPanel()
        self._inspector.set_callbacks(
            self._rename_node,
            self._test_node,
            self._start_services,
            self._restart_services,
            self._stop_services,
        )

        self._log_panel = LogPanel()
        self._scene.flow_changed.connect(lambda: self._log_panel.append("Flow graph updated."))
        self.status_ready.connect(self._apply_status)

        self.setMenuWidget(self._build_header())
        self.setCentralWidget(self._build_body())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(8000)

        self._load_flows()
        self._refresh_status()
        self._log_panel.append("Flow editor ready.")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet("background: #121212; border-bottom: 1px solid rgba(255,255,255,0.1);")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)

        brand = QLabel("proxyEverywhere")
        brand.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 800;")
        layout.addWidget(brand)

        subtitle = QLabel("Flow Builder")
        subtitle.setStyleSheet("color: #2e66ff; font-size: 11px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;")
        layout.addWidget(subtitle)
        layout.addStretch()

        controls = [
            ("Load", self._load_flows, False),
            ("Save", self._save_flows, False),
            ("Clear", self._clear_canvas, False),
            ("Start Services", self._start_services, False),
            ("Restart Services", self._restart_services, False),
            ("Save & Restart", self._save_and_restart, True),
        ]
        for text, handler, primary in controls:
            btn = QPushButton(text)
            btn.setFixedHeight(34)
            btn.setStyleSheet(_button_style(primary))
            btn.clicked.connect(handler)
            layout.addWidget(btn)
        return header

    def _build_body(self) -> QWidget:
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._view, 1)
        center_layout.addWidget(self._log_panel, 0)

        outer.addWidget(self._sidebar)
        outer.addWidget(center, 1)
        outer.addWidget(self._inspector)
        return root

    def _refresh_status(self):
        def worker():
            try:
                current = status()
            except Exception as exc:
                self._log_panel.append(f"Status refresh failed: {exc}")
                return
            self.status_ready.emit(current)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_status(self, current: dict[str, dict[str, object]]):
        self._inspector.update_services(current)
        for node in self._scene.all_nodes():
            if node.kind != "input":
                continue
            provider = str(node.meta.get("provider", ""))
            service_name = _service_name_for_provider(provider)
            if not service_name:
                continue
            healthy = bool(current.get(service_name, {}).get("healthy"))
            node.update_meta(status="online" if healthy else "offline")
        selected = self._selected_node()
        self._inspector.show_node(selected)

    def _selected_node(self) -> FlowNode | None:
        for item in self._scene.selectedItems():
            if isinstance(item, FlowNode):
                return item
        return None

    def _sync_selection(self):
        self._inspector.show_node(self._selected_node())

    def _on_place_requested(self, kind: str, label: str, meta: dict[str, Any]):
        self._pending_kind = kind
        self._pending_label = label
        self._pending_meta = meta
        self._view.set_placement_mode(True)
        self._log_panel.append(f"Placement armed for {label}. Click on the canvas to place it.")

    def _on_node_placed(self, scene_pos: QPointF):
        if not self._pending_kind:
            return
        meta = dict(self._pending_meta)
        if self._pending_kind == "input" and meta.get("subtype") == "proxy":
            provider = str(meta.get("provider", "codex"))
            meta.setdefault("port", LOCAL_PROVIDER_PORTS.get(provider, 0))
        node = self._scene.add_node(self._pending_kind, self._pending_label or "Node", scene_pos, meta)
        node.setSelected(True)
        self._pending_kind = None
        self._pending_label = None
        self._pending_meta = {}
        self._view.set_placement_mode(False)
        self._log_panel.append(f"Placed {node.label}.")

    def _rename_node(self, node: FlowNode, new_name: str):
        node.label = new_name
        node.update()
        self._inspector.show_node(node)
        self._log_panel.append(f"Renamed node to {new_name}.")

    def _test_node(self, node: FlowNode):
        if node.kind != "input":
            return
        provider = str(node.meta.get("provider", ""))
        service_name = _service_name_for_provider(provider)
        current = status()
        healthy = bool(current.get(service_name, {}).get("healthy")) if service_name else False
        node.update_meta(status="online" if healthy else "offline")
        self._inspector.show_node(node)
        result = "ONLINE" if healthy else "OFFLINE"
        self._log_panel.append(f"Tested {node.label}: {result}.")

    def _clear_canvas(self):
        self._scene.clear()
        self._inspector.show_node(None)
        self._log_panel.append("Canvas cleared.")

    def _save_flows(self):
        flows = self._scene_to_flows()
        cfg = load_config()
        cfg.flows = flows
        save_config(cfg)
        self._log_panel.append(f"Saved {len(flows)} flow(s).")

    def _save_and_restart(self):
        self._save_flows()
        self._restart_services()

    def _start_services(self):
        threading.Thread(target=start_all, daemon=True).start()
        self._log_panel.append("Starting services...")

    def _restart_services(self):
        threading.Thread(target=restart_all, daemon=True).start()
        self._log_panel.append("Restarting services...")

    def _stop_services(self):
        threading.Thread(target=stop_all, daemon=True).start()
        self._log_panel.append("Stopping services...")

    def _load_flows(self):
        self._scene.clear()
        cfg = load_config()
        flows = normalized_flows(cfg.flows)
        self._flow_models_by_id = {str(flow.get("id")): list(flow.get("models", [])) for flow in flows}

        local_ports = {
            "codex": cfg.codex_port,
            "gemini": cfg.gemini_port,
            "claude": cfg.claude_port,
        }

        for flow in flows:
            if not flow.get("enabled", True):
                continue
            layout = flow.get("layout", {})
            source = flow.get("source", {})
            source_pos = layout.get("source", {"x": 60, "y": 90})
            middle_pos = layout.get("middle", {"x": 340, "y": 90})
            output_pos = layout.get("output", {"x": 620, "y": 90})

            if source.get("kind") == "external":
                source_format = str(source.get("format", "openai"))
                source_label = f"{FORMAT_PROTOCOLS.get(source_format, source_format.title())} API"
                source_meta = {
                    "provider": source_format,
                    "subtype": "api",
                    "protocol": FORMAT_PROTOCOLS.get(source_format, source_format.title()),
                    "base_url": source.get("base_url", ""),
                    "api_key": source.get("api_key", ""),
                    "flow_id": flow.get("id"),
                    "status": "offline",
                }
            else:
                provider = str(source.get("provider", "codex"))
                source_label = f"{provider.title()} Proxy"
                source_meta = {
                    "provider": provider,
                    "subtype": "proxy",
                    "protocol": PROVIDER_PROTOCOLS.get(provider, provider.title()),
                    "port": local_ports.get(provider, 0),
                    "flow_id": flow.get("id"),
                    "status": "offline",
                }

            source_node = self._scene.add_node(
                "input",
                source_label,
                QPointF(source_pos["x"], source_pos["y"]),
                source_meta,
            )
            transform_node = self._scene.add_node(
                "transform",
                "LiteLLM Transform",
                QPointF(middle_pos["x"], middle_pos["y"]),
                {"engine": "litellm"},
            )
            if source_node.output_port and transform_node.input_port:
                self._scene.add_edge(source_node.output_port, transform_node.input_port)

            for index, output in enumerate(flow.get("outputs", [])):
                fmt = str(output.get("format", "anthropic"))
                node = self._scene.add_node(
                    "output",
                    f"{FORMAT_PROTOCOLS.get(fmt, fmt.title())} Output",
                    QPointF(output_pos["x"], output_pos["y"] + index * (NODE_H + 30)),
                    {
                        "format": fmt,
                        "protocol": FORMAT_PROTOCOLS.get(fmt, fmt.title()),
                        "port": int(output.get("port", cfg.litellm_port)),
                        "api_key": output.get("api_key", cfg.litellm_master_key),
                    },
                )
                if transform_node.output_port and node.input_port:
                    self._scene.add_edge(transform_node.output_port, node.input_port)

        self._inspector.show_node(None)
        self._log_panel.append(f"Loaded {len(flows)} configured flow(s).")

    def _scene_to_flows(self) -> list[dict[str, Any]]:
        nodes = self._scene.all_nodes()
        edges = self._scene.all_edges()
        flows: list[dict[str, Any]] = []
        input_nodes = [node for node in nodes if node.kind == "input"]

        for source_node in input_nodes:
            connected_transforms = [
                edge.dest_port.node
                for edge in edges
                if edge.source_port.node is source_node and edge.dest_port and edge.dest_port.node.kind == "transform"
            ]
            for transform_node in connected_transforms:
                connected_outputs = [
                    edge.dest_port.node
                    for edge in edges
                    if edge.source_port.node is transform_node and edge.dest_port and edge.dest_port.node.kind == "output"
                ]
                if not connected_outputs:
                    continue

                provider = str(source_node.meta.get("provider", "custom"))
                flow_id = str(source_node.meta.get("flow_id") or f"{provider}_{uuid.uuid4().hex[:6]}")
                outputs = []
                for output_node in connected_outputs:
                    outputs.append(
                        {
                            "format": str(output_node.meta.get("format", "anthropic")),
                            "port": int(output_node.meta.get("port", 4000)),
                            "api_key": str(output_node.meta.get("api_key", "litellm-local-test-key")),
                        }
                    )

                if source_node.meta.get("subtype") == "proxy" and provider in {"codex", "gemini", "claude"}:
                    source_config: dict[str, Any] = {"kind": "local", "provider": provider}
                else:
                    source_config = {
                        "kind": "external",
                        "format": str(source_node.meta.get("protocol", "OpenAI")).lower(),
                        "base_url": str(source_node.meta.get("base_url", "")),
                        "api_key": str(source_node.meta.get("api_key", "")),
                    }

                flow = {
                    "id": flow_id,
                    "name": f"{provider.title()} flow",
                    "enabled": True,
                    "source": source_config,
                    "middle": {"kind": "litellm"},
                    "outputs": outputs,
                    "models": self._flow_models_by_id.get(flow_id, []),
                    "layout": {
                        "source": {"x": int(source_node.pos().x()), "y": int(source_node.pos().y())},
                        "middle": {"x": int(transform_node.pos().x()), "y": int(transform_node.pos().y())},
                        "output": {"x": int(connected_outputs[0].pos().x()), "y": int(connected_outputs[0].pos().y())},
                    },
                }
                flows.append(flow)

        return flows


def run_native_ui():
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("SF Pro Display", 13))
    window = MainWindow()
    window.show()
    app.exec()
