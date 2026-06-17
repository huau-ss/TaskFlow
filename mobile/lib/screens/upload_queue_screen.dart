import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/upload_queue.dart';

class UploadQueueScreen extends StatefulWidget {
  const UploadQueueScreen({super.key, required this.uploadQueue});

  final UploadQueue uploadQueue;

  @override
  State<UploadQueueScreen> createState() => _UploadQueueScreenState();
}

class _UploadQueueScreenState extends State<UploadQueueScreen> with WidgetsBindingObserver {
  List<Map<String, dynamic>> _items = [];
  Timer? _refreshTimer;
  bool _isSelectingFile = false;
  
  static const _pickerChannel = MethodChannel('com.taskflow/document_picker');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    _refreshTimer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _refreshTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
    }
  }

  Future<void> _refresh() async {
    final items = await widget.uploadQueue.getAll();
    if (mounted) setState(() => _items = items);
  }

  Future<void> _pickAndUploadFile() async {
    if (_isSelectingFile) return;
    setState(() => _isSelectingFile = true);

    try {
      final result = await _pickerChannel.invokeMethod<Map<dynamic, dynamic>>('pickAudioFile');

      if (result != null) {
        final path = result['path'] as String?;
        final name = result['name'] as String?;
        
        if (path != null) {
          final title = await _showTitleDialog(fileName: name ?? '音频文件');
          await widget.uploadQueue.enqueue(
            localPath: path,
            title: title,
          );
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('文件已添加到上传队列')),
          );
          _refresh();
        }
      }
    } on PlatformException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('选择文件失败: ${e.message}')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('选择文件失败: $e')),
      );
    } finally {
      if (mounted) setState(() => _isSelectingFile = false);
    }
  }

  Future<String?> _showTitleDialog({required String fileName}) async {
    final controller = TextEditingController(text: fileName);
    return showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('设置标题'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: '会议标题',
            border: OutlineInputBorder(),
          ),
          onSubmitted: (value) => Navigator.pop(context, value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, fileName),
            child: const Text('使用文件名'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim().isEmpty ? fileName : controller.text.trim()),
            child: const Text('确定'),
          ),
        ],
      ),
    );
  }

  Color _statusColor(String? status) {
    switch (status) {
      case 'uploaded':
        return Colors.green;
      case 'uploading':
        return Colors.blue;
      case 'failed':
        return Colors.red;
      default:
        return Colors.orange;
    }
  }

  String _statusText(String? status) {
    switch (status) {
      case 'pending_upload':
        return '等待上传';
      case 'uploading':
        return '上传中';
      case 'uploaded':
        return '已上传';
      case 'failed':
        return '上传失败';
      default:
        return status ?? '未知';
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.cloud_upload_outlined, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('上传队列为空', style: TextStyle(fontSize: 18, color: Colors.grey)),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: _isSelectingFile ? null : _pickAndUploadFile,
              icon: _isSelectingFile
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.add),
              label: Text(_isSelectingFile ? '选择中...' : '选择音频文件'),
            ),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: Stack(
        children: [
          ListView.builder(
            itemCount: _items.length,
            itemBuilder: (context, index) {
              final item = _items[index];
              final status = item['status'] as String?;
              return ListTile(
                leading: Icon(Icons.audio_file, color: _statusColor(status)),
                title: Text(item['title']?.toString() ?? item['local_path'].toString().split('/').last),
                subtitle: Text(
                  _statusText(status),
                  style: TextStyle(color: _statusColor(status)),
                ),
                trailing: status == 'failed'
                    ? IconButton(
                        icon: const Icon(Icons.refresh),
                        onPressed: () async {
                          await widget.uploadQueue.retryItem(item['id'] as int);
                          _refresh();
                        },
                      )
                    : status == 'pending_upload'
                        ? const Icon(Icons.schedule, color: Colors.orange)
                        : status == 'uploading'
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.check_circle, color: Colors.green),
              );
            },
          ),
          Positioned(
            right: 16,
            bottom: 16,
            child: FloatingActionButton(
              onPressed: _isSelectingFile ? null : _pickAndUploadFile,
              child: _isSelectingFile
                  ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.add),
            ),
          ),
        ],
      ),
    );
  }
}
