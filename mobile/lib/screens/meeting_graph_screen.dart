import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../services/api_service.dart';
import 'meeting_detail_screen.dart';

class MeetingGraphScreen extends StatefulWidget {
  const MeetingGraphScreen({super.key, required this.api});

  final ApiService api;

  @override
  State<MeetingGraphScreen> createState() => _MeetingGraphScreenState();
}

class _MeetingGraphScreenState extends State<MeetingGraphScreen> {
  Map<String, dynamic>? _graphData;
  bool _loading = true;
  bool _analyzing = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadGraph();
  }

  Future<void> _loadGraph() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _graphData = await widget.api.getMeetingGraph();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _analyzeRelations() async {
    setState(() => _analyzing = true);
    try {
      final result = await widget.api.analyzeMeetingRelations();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '分析了 ${result['analyzed_count']} 个会议，'
            '新增 ${result['new_relations']} 条关联',
          ),
        ),
      );
      await _loadGraph();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('分析失败: $e')),
      );
    } finally {
      if (mounted) setState(() => _analyzing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('会议关联图谱'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadGraph,
          ),
        ],
      ),
      body: _buildBody(),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _analyzing ? null : _analyzeRelations,
        icon: _analyzing
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
              )
            : const Icon(Icons.auto_fix_high),
        label: Text(_analyzing ? '分析中...' : 'AI 分析关联'),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 64, color: Colors.red),
            const SizedBox(height: 16),
            Text('加载失败: $_error'),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: _loadGraph, child: const Text('重试')),
          ],
        ),
      );
    }

    final nodes = (_graphData?['nodes'] as List<dynamic>?) ?? [];
    final edges = (_graphData?['edges'] as List<dynamic>?) ?? [];

    if (nodes.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.hub_outlined, size: 80, color: Colors.grey),
            SizedBox(height: 16),
            Text(
              '暂无会议数据',
              style: TextStyle(fontSize: 18, color: Colors.grey),
            ),
            SizedBox(height: 8),
            Text(
              '上传会议录音后，即可查看会议关联图谱',
              style: TextStyle(color: Colors.grey),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        _buildLegend(),
        Expanded(
          child: _MeetingGraphView(
            nodes: nodes.cast<Map<String, dynamic>>(),
            edges: edges.cast<Map<String, dynamic>>(),
            onNodeTap: (node) => _openMeeting(node),
          ),
        ),
        _buildRelationList(edges.cast<Map<String, dynamic>>(), nodes.cast<Map<String, dynamic>>()),
      ],
    );
  }

  Widget _buildLegend() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Wrap(
        spacing: 16,
        runSpacing: 4,
        children: [
          _legendItem(Colors.blue, '后续会议'),
          _legendItem(Colors.orange, '相关会议'),
          _legendItem(Colors.red, '前置依赖'),
        ],
      ),
    );
  }

  Widget _legendItem(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 16,
          height: 3,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 12)),
      ],
    );
  }

  void _openMeeting(Map<String, dynamic> node) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => MeetingDetailScreen(api: widget.api, meeting: node),
      ),
    );
  }

  Widget _buildRelationList(
    List<Map<String, dynamic>> edges,
    List<Map<String, dynamic>> nodes,
  ) {
    if (edges.isEmpty) {
      return const SizedBox.shrink();
    }

    final nodeMap = {for (var n in nodes) n['id']: n};

    return Container(
      height: 160,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        border: Border(top: BorderSide(color: Colors.grey.shade300)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text(
              '已发现 ${edges.length} 条关联',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
            ),
          ),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              itemCount: edges.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final edge = edges[index];
                final source = nodeMap[edge['source']];
                final target = nodeMap[edge['target']];

                return ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: _relationTypeIcon(edge['relation_type'] as String),
                  title: Text(
                    '${source?['title'] ?? '会议${edge['source']}'} → ${target?['title'] ?? '会议${edge['target']}'}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: edge['reason'] != null
                      ? Text(
                          edge['reason']!,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 11),
                        )
                      : null,
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '${((edge['confidence'] as double) * 100).toStringAsFixed(0)}%',
                        style: const TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                      IconButton(
                        icon: const Icon(Icons.delete_outline, size: 18),
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints(),
                        onPressed: () => _deleteRelation(edge['id'] as int),
                      ),
                    ],
                  ),
                  onTap: () => _openMeeting(target ?? {}),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _relationTypeIcon(String type) {
    IconData icon;
    Color color;
    switch (type) {
      case 'follow_up':
        icon = Icons.arrow_forward;
        color = Colors.blue;
        break;
      case 'prerequisite':
        icon = Icons.lock_outline;
        color = Colors.red;
        break;
      default:
        icon = Icons.link;
        color = Colors.orange;
    }
    return Icon(icon, color: color, size: 20);
  }

  Future<void> _deleteRelation(int relationId) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除关联'),
        content: const Text('确定要删除这条会议关联吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    try {
      await widget.api.deleteMeetingRelation(relationId);
      await _loadGraph();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('删除失败: $e')),
      );
    }
  }
}

class _MeetingGraphView extends StatefulWidget {
  const _MeetingGraphView({
    required this.nodes,
    required this.edges,
    required this.onNodeTap,
  });

  final List<Map<String, dynamic>> nodes;
  final List<Map<String, dynamic>> edges;
  final void Function(Map<String, dynamic>) onNodeTap;

  @override
  State<_MeetingGraphView> createState() => _MeetingGraphViewState();
}

class _MeetingGraphViewState extends State<_MeetingGraphView> {
  Map<int, Offset> _positions = {};
  Offset _offset = Offset.zero;
  double _scale = 1.0;

  @override
  void initState() {
    super.initState();
    _initPositions();
  }

  @override
  void didUpdateWidget(_MeetingGraphView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.nodes.length != oldWidget.nodes.length ||
        widget.edges.length != oldWidget.edges.length) {
      _initPositions();
    }
  }

  void _initPositions() {
    final random = math.Random(42);
    final size = MediaQuery.of(context).size;
    final center = Offset(size.width / 2, size.height / 2);

    _positions = {};
    for (var node in widget.nodes) {
      final id = node['id'] as int;
      final angle = random.nextDouble() * 2 * math.pi;
      final radius = 80.0 + random.nextDouble() * 60;
      _positions[id] = center + Offset.fromDirection(angle, radius);
    }
    _offset = Offset.zero;
    _scale = 1.0;
  }

  void _applyForceDirected() {
    const iterations = 50;
    const repulsion = 5000.0;
    const attraction = 0.02;
    const damping = 0.85;

    final velocities = <int, Offset>{};
    for (var node in widget.nodes) {
      velocities[node['id'] as int] = Offset.zero;
    }

    for (var i = 0; i < iterations; i++) {
      for (var nodeA in widget.nodes) {
        final idA = nodeA['id'] as int;
        final posA = _positions[idA]!;
        var force = Offset.zero;

        // 节点间的斥力
        for (var nodeB in widget.nodes) {
          final idB = nodeB['id'] as int;
          if (idA == idB) continue;
          final posB = _positions[idB]!;
          final delta = posA - posB;
          final dist = delta.distance.clamp(1.0, 500.0);
          force += delta / dist * (repulsion / (dist * dist));
        }

        // 边的引力
        for (var edge in widget.edges) {
          final sourceId = edge['source'] as int;
          final targetId = edge['target'] as int;
          if (idA == sourceId) {
            final targetPos = _positions[targetId]!;
            force += (targetPos - posA) * attraction;
          } else if (idA == targetId) {
            final sourcePos = _positions[sourceId]!;
            force += (sourcePos - posA) * attraction;
          }
        }

        velocities[idA] = (velocities[idA]! + force) * damping;
      }

      for (var node in widget.nodes) {
        final id = node['id'] as int;
        _positions[id] = _positions[id]! + velocities[id]!;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.nodes.isEmpty) return const SizedBox.shrink();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _applyForceDirected();
      if (mounted) setState(() {});
    });

    return GestureDetector(
      onScaleStart: (_) {},
      onScaleUpdate: (details) {
        setState(() {
          _scale = (_scale * details.scale).clamp(0.3, 3.0);
          _offset += details.focalPointDelta;
        });
      },
      child: ClipRect(
        child: CustomPaint(
          painter: _GraphPainter(
            nodes: widget.nodes,
            edges: widget.edges,
            positions: _positions,
            offset: _offset,
            scale: _scale,
          ),
          child: Stack(
            children: [
              for (var node in widget.nodes)
                _buildNodeWidget(node),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildNodeWidget(Map<String, dynamic> node) {
    final id = node['id'] as int;
    final pos = _positions[id];
    if (pos == null) return const SizedBox.shrink();

    final status = node['status'] as String? ?? 'uploaded';
    Color statusColor;
    switch (status) {
      case 'transcribed':
        statusColor = Colors.green;
        break;
      case 'transcribing':
        statusColor = Colors.orange;
        break;
      case 'failed':
        statusColor = Colors.red;
        break;
      default:
        statusColor = Colors.grey;
    }

    final title = node['title']?.toString() ?? '会议$id';
    final screenPos = (pos + _offset) * _scale;

    return Positioned(
      left: screenPos.dx - 60,
      top: screenPos.dy - 20,
      child: GestureDetector(
        onTap: () => widget.onNodeTap(node),
        child: Column(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.primaryContainer,
                shape: BoxShape.circle,
                border: Border.all(color: statusColor, width: 2),
              ),
              child: Center(
                child: Text(
                  title.isNotEmpty ? title[0] : '?',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Theme.of(context).colorScheme.onPrimaryContainer,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 4),
            SizedBox(
              width: 120,
              child: Text(
                title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 11),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _GraphPainter extends CustomPainter {
  _GraphPainter({
    required this.nodes,
    required this.edges,
    required this.positions,
    required this.offset,
    required this.scale,
  });

  final List<Map<String, dynamic>> nodes;
  final List<Map<String, dynamic>> edges;
  final Map<int, Offset> positions;
  final Offset offset;
  final double scale;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(scale);
    canvas.translate(offset.dx, offset.dy);

    for (var edge in edges) {
      final sourcePos = positions[edge['source'] as int];
      final targetPos = positions[edge['target'] as int];
      if (sourcePos == null || targetPos == null) continue;

      Color color;
      switch (edge['relation_type'] as String) {
        case 'follow_up':
          color = Colors.blue;
          break;
        case 'prerequisite':
          color = Colors.red;
          break;
        default:
          color = Colors.orange;
      }

      final paint = Paint()
        ..color = color.withOpacity(0.7)
        ..strokeWidth = 1.5
        ..style = PaintingStyle.stroke;

      // 画线
      canvas.drawLine(sourcePos, targetPos, paint);

      // 画箭头
      _drawArrow(canvas, sourcePos, targetPos, color);
    }

    canvas.restore();
  }

  void _drawArrow(Canvas canvas, Offset from, Offset to, Color color) {
    final direction = (to - from);
    final length = direction.distance;
    if (length < 20) return;

    final normalized = direction / length;
    final midPoint = from + normalized * (length * 0.7);

    // 线条终点稍微缩短
    final arrowTip = from + normalized * (length - 20);

    const arrowSize = 8.0;
    final perpendicular = Offset(-normalized.dy, normalized.dx);

    final arrowLeft = arrowTip - normalized * arrowSize + perpendicular * arrowSize * 0.5;
    final arrowRight = arrowTip - normalized * arrowSize - perpendicular * arrowSize * 0.5;

    final arrowPath = Path()
      ..moveTo(arrowTip.dx, arrowTip.dy)
      ..lineTo(arrowLeft.dx, arrowLeft.dy)
      ..lineTo(arrowRight.dx, arrowRight.dy)
      ..close();

    canvas.drawPath(
      arrowPath,
      Paint()
        ..color = color.withOpacity(0.7)
        ..style = PaintingStyle.fill,
    );
  }

  @override
  bool shouldRepaint(_GraphPainter oldDelegate) {
    return true;
  }
}
