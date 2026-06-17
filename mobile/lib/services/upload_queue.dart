import 'dart:async';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'api_service.dart';

enum UploadStatus { pending_upload, uploading, uploaded, failed }

class UploadQueue {
  UploadQueue({required this.api});

  final ApiService api;
  Database? _db;
  Timer? _timer;
  bool _processing = false;

  static const _maxRetries = 5;

  Future<void> init() async {
    await api.loadToken();
    final dbPath = p.join(await getDatabasesPath(), 'upload_queue.db');
    _db = await openDatabase(
      dbPath,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE upload_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_path TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL DEFAULT 'pending_upload',
            retry_count INTEGER NOT NULL DEFAULT 0,
            meeting_id INTEGER,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
          )
        ''');
      },
      onOpen: (db) async {
        // one-time migration for older camelCase statuses
        await db.execute("UPDATE upload_queue SET status='pending_upload' WHERE status='pendingUpload'");
      },
    );
  }

  void startBackgroundProcessor({Duration interval = const Duration(seconds: 30)}) {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => processQueue());
    processQueue();
  }

  void stopBackgroundProcessor() {
    _timer?.cancel();
    _timer = null;
  }

  Future<int> enqueue({required String localPath, String? title}) async {
    final now = DateTime.now().toIso8601String();
    return _db!.insert('upload_queue', {
      'local_path': localPath,
      'title': title,
      'status': UploadStatus.pending_upload.name,
      'retry_count': 0,
      'created_at': now,
      'updated_at': now,
    });
  }

  Future<List<Map<String, dynamic>>> getAll() async {
    return _db!.query('upload_queue', orderBy: 'created_at DESC');
  }

  Future<List<Map<String, dynamic>>> getPending() async {
    return _db!.query(
      'upload_queue',
      where: 'status IN (?, ?)',
      whereArgs: [UploadStatus.pending_upload.name, UploadStatus.failed.name],
      orderBy: 'created_at ASC',
    );
  }

  Future<void> processQueue() async {
    if (_processing || !api.isAuthenticated) return;
    _processing = true;
    try {
      final pending = await getPending();
      for (final item in pending) {
        if ((item['retry_count'] as int) >= _maxRetries) continue;
        await _uploadItem(item);
      }
    } finally {
      _processing = false;
    }
  }

  Future<void> _uploadItem(Map<String, dynamic> item) async {
    final id = item['id'] as int;
    final path = item['local_path'] as String;
    final file = File(path);
    if (!await file.exists()) {
      await _updateStatus(id, UploadStatus.failed, error: 'Local file missing');
      return;
    }

    await _updateStatus(id, UploadStatus.uploading);
    try {
      final result = await api.uploadMeeting(
        file: file,
        title: item['title'] as String?,
      );
      await _db!.update(
        'upload_queue',
        {
          'status': UploadStatus.uploaded.name,
          'meeting_id': result['id'],
          'error_message': null,
          'updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [id],
      );
    } catch (e) {
      final retries = (item['retry_count'] as int) + 1;
      await _db!.update(
        'upload_queue',
        {
          'status': UploadStatus.failed.name,
          'retry_count': retries,
          'error_message': e.toString(),
          'updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [id],
      );
    }
  }

  Future<void> _updateStatus(int id, UploadStatus status, {String? error}) async {
    await _db!.update(
      'upload_queue',
      {
        'status': status.name,
        'error_message': error,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> retryItem(int id) async {
    await _db!.update(
      'upload_queue',
      {
        'status': UploadStatus.pending_upload.name,
        'retry_count': 0,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    await processQueue();
  }
}
