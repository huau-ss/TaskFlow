import 'dart:convert';
import 'dart:io';
import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:permission_handler/permission_handler.dart';

import '../services/api_service.dart';

class VoicePrintManagementScreen extends StatefulWidget {
  const VoicePrintManagementScreen({super.key, required this.api});

  final ApiService api;

  @override
  State<VoicePrintManagementScreen> createState() => _VoicePrintManagementScreenState();
}

class _VoicePrintManagementScreenState extends State<VoicePrintManagementScreen> {
  List<dynamic> _employees = [];
  List<dynamic> _voicePrints = [];
  bool _loading = true;
  bool _recording = false;
  String? _selectedEmployeeId;
  String? _recordingPath;
  String? _uploadFilePath;
  String? _uploadFileName;
  AudioRecorder? _recorder;
  int _recordingSeconds = 0;
  Timer? _recordingTimer;
  int _inputMode = 0; // 0: 录音, 1: 文件上传

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void dispose() {
    _recordingTimer?.cancel();
    _recorder?.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    try {
      _employees = await widget.api.listEmployees();
      if (_employees.isNotEmpty && _selectedEmployeeId == null) {
        _selectedEmployeeId = _employees.first['id'].toString();
        await _loadVoicePrints();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('加载失败: $e')));
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadVoicePrints() async {
    if (_selectedEmployeeId == null) return;
    try {
      _voicePrints = await widget.api.getEmployeeVoicePrints(int.parse(_selectedEmployeeId!));
    } catch (e) {
      _voicePrints = [];
    }
    if (mounted) setState(() {});
  }

  Future<void> _startRecording() async {
    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('需要麦克风权限')),
        );
      }
      return;
    }

    final dir = await getTemporaryDirectory();
    _recordingPath = '${dir.path}/voiceprint_${DateTime.now().millisecondsSinceEpoch}.wav';

    _recorder ??= AudioRecorder();
    await _recorder!.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: _recordingPath!,
    );

    _recordingTimer?.cancel();

    setState(() {
      _recording = true;
      _recordingSeconds = 0;
    });

    _recordingTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      setState(() => _recordingSeconds++);
      // 自动停止：30秒
      if (_recordingSeconds >= 30) {
        _stopRecording();
      }
    });
  }

  Future<void> _stopRecording() async {
    _recordingTimer?.cancel();
    final path = await _recorder?.stop();
    if (!mounted) return;
    setState(() => _recording = false);
    if (path != null) {
      _recordingPath = path;
      _uploadVoicePrint();
    }
  }

  Future<void> _pickAudioFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.audio,
        allowMultiple: false,
      );
      if (result != null && result.files.isNotEmpty) {
        final file = result.files.first;
        setState(() {
          _uploadFilePath = file.path;
          _uploadFileName = file.name;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('选择文件失败: $e')),
        );
      }
    }
  }

  Future<void> _uploadPickedFile() async {
    if (_uploadFilePath == null || _selectedEmployeeId == null) return;

    final file = File(_uploadFilePath!);
    if (!await file.exists()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('文件不存在')),
        );
      }
      return;
    }

    try {
      await widget.api.registerVoicePrintFromFile(
        employeeId: int.parse(_selectedEmployeeId!),
        file: file,
        note: '上传音频文件: $_uploadFileName',
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('声纹上传成功，等待管理员验证')),
        );
        setState(() {
          _uploadFilePath = null;
          _uploadFileName = null;
        });
        await _loadVoicePrints();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('上传失败: $e')),
        );
      }
    }
  }

  Future<void> _clearPickedFile() async {
    setState(() {
      _uploadFilePath = null;
      _uploadFileName = null;
    });
  }

  Future<void> _uploadVoicePrint() async {
    if (_recordingPath == null || _selectedEmployeeId == null) return;

    final file = File(_recordingPath!);
    if (!await file.exists()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('录音文件不存在')),
        );
      }
      return;
    }

    final bytes = await file.readAsBytes();
    final base64Audio = base64Encode(bytes);

    try {
      await widget.api.registerVoicePrint(
        employeeId: int.parse(_selectedEmployeeId!),
        audioBase64: base64Audio,
        note: 'Flutter 录音',
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('声纹上传成功，等待管理员验证')),
        );
        await _loadVoicePrints();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('上传失败: $e')),
        );
      }
    }
  }

  Future<void> _verifyVoicePrint(int id, bool verified) async {
    try {
      await widget.api.verifyVoicePrint(id, verified);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(verified ? '已验证' : '已取消验证')),
        );
        await _loadVoicePrints();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('操作失败: $e')),
        );
      }
    }
  }

  Future<void> _deleteVoicePrint(int id) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('确认删除'),
        content: const Text('确定要删除这条声纹吗？'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('删除', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        await widget.api.deleteVoicePrint(id);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已删除')));
          await _loadVoicePrints();
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('删除失败: $e')),
          );
        }
      }
    }
  }

  String _formatDuration(int seconds) {
    final min = seconds ~/ 60;
    final sec = seconds % 60;
    return '${min.toString().padLeft(2, '0')}:${sec.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('声纹管理'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                _buildEmployeeSelector(),
                const Divider(height: 1),
                _buildInputModeSelector(),
                const Divider(height: 1),
                _buildRecordingSection(),
                const Divider(height: 1),
                Expanded(child: _buildVoicePrintList()),
              ],
            ),
    );
  }

  Widget _buildEmployeeSelector() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          const Text('选择员工: ', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(width: 8),
          Expanded(
            child: DropdownButton<String>(
              value: _selectedEmployeeId,
              isExpanded: true,
              items: _employees.map<DropdownMenuItem<String>>((e) {
                return DropdownMenuItem<String>(
                  value: e['id'].toString(),
                  child: Text(e['name']?.toString() ?? '员工 ${e['id']}'),
                );
              }).toList(),
              onChanged: (v) {
                setState(() => _selectedEmployeeId = v);
                _loadVoicePrints();
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInputModeSelector() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Text('音频来源: ', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(width: 8),
          ChoiceChip(
            label: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.mic, size: 18),
                SizedBox(width: 4),
                Text('录音'),
              ],
            ),
            selected: _inputMode == 0,
            onSelected: (selected) {
              if (selected) setState(() => _inputMode = 0);
            },
          ),
          const SizedBox(width: 8),
          ChoiceChip(
            label: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.upload_file, size: 18),
                SizedBox(width: 4),
                Text('上传文件'),
              ],
            ),
            selected: _inputMode == 1,
            onSelected: (selected) {
              if (selected) setState(() => _inputMode = 1);
            },
          ),
        ],
      ),
    );
  }

  Widget _buildRecordingSection() {
    if (_inputMode == 1) {
      return _buildFileUploadSection();
    }
    return _buildRecordingWidget();
  }

  Widget _buildFileUploadSection() {
    final hasFile = _uploadFilePath != null;
    return Container(
      padding: const EdgeInsets.all(16),
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.audio_file, color: hasFile ? Colors.green : Colors.grey),
              const SizedBox(width: 8),
              Expanded(
                child: hasFile
                    ? Text(
                        _uploadFileName ?? '已选择音频文件',
                        style: const TextStyle(fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis,
                      )
                    : const Text('选择本地音频文件进行声纹分析'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _pickAudioFile,
                  icon: const Icon(Icons.folder_open),
                  label: Text(hasFile ? '重新选择' : '选择文件'),
                ),
              ),
              if (hasFile) ...[
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _uploadPickedFile,
                    icon: const Icon(Icons.upload),
                    label: const Text('上传声纹'),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _clearPickedFile,
                  icon: const Icon(Icons.close),
                  tooltip: '清除文件',
                ),
              ],
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '支持 WAV、MP3、M4A 等常见音频格式，建议使用 5-30 秒的清晰人声录音',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
          ),
        ],
      ),
    );
  }

  Widget _buildRecordingWidget() {
    return Container(
      padding: const EdgeInsets.all(16),
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Column(
        children: [
          Row(
            children: [
              Icon(
                Icons.mic,
                color: _recording ? Colors.red : Colors.grey,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _recording
                      ? '录音中... ${_formatDuration(_recordingSeconds)} / 00:30'
                      : '点击开始录音 (建议 5-30 秒)',
                  style: TextStyle(
                    color: _recording ? Colors.red : null,
                    fontWeight: _recording ? FontWeight.bold : null,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: _recording
                ? OutlinedButton.icon(
                    onPressed: _stopRecording,
                    icon: const Icon(Icons.stop, color: Colors.red),
                    label: const Text('停止录音'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.red,
                      side: const BorderSide(color: Colors.red),
                    ),
                  )
                : FilledButton.icon(
                    onPressed: _startRecording,
                    icon: const Icon(Icons.mic),
                    label: const Text('开始录音'),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildVoicePrintList() {
    if (_voicePrints.isEmpty) {
      return const Center(
        child: Text('暂无声纹记录\n选择员工后录制声纹', textAlign: TextAlign.center),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(8),
      itemCount: _voicePrints.length,
      itemBuilder: (context, index) {
        final vp = _voicePrints[index] as Map<String, dynamic>;
        final isVerified = vp['is_verified'] as bool? ?? false;
        final createdAt = vp['created_at'] as String? ?? '';

        return Card(
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: isVerified ? Colors.green : Colors.orange,
              child: Icon(
                isVerified ? Icons.verified : Icons.pending,
                color: Colors.white,
                size: 20,
              ),
            ),
            title: Text(isVerified ? '已验证' : '待验证'),
            subtitle: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (vp['note'] != null) Text('备注: ${vp['note']}'),
                if (vp['audio_duration'] != null)
                  Text('时长: ${(vp['audio_duration'] as num).toStringAsFixed(1)}秒'),
                Text('创建: $createdAt', style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
            isThreeLine: true,
            trailing: PopupMenuButton<String>(
              onSelected: (action) {
                final id = vp['id'] as int;
                switch (action) {
                  case 'verify':
                    _verifyVoicePrint(id, !isVerified);
                    break;
                  case 'delete':
                    _deleteVoicePrint(id);
                    break;
                }
              },
              itemBuilder: (ctx) => [
                PopupMenuItem(
                  value: 'verify',
                  child: Row(
                    children: [
                      Icon(isVerified ? Icons.close : Icons.check, size: 20),
                      const SizedBox(width: 8),
                      Text(isVerified ? '取消验证' : '标记已验证'),
                    ],
                  ),
                ),
                const PopupMenuItem(
                  value: 'delete',
                  child: Row(
                    children: [
                      Icon(Icons.delete, size: 20, color: Colors.red),
                      SizedBox(width: 8),
                      Text('删除', style: TextStyle(color: Colors.red)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
