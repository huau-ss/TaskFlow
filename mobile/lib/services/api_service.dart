import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  ApiService({required String baseUrl}) : _dio = Dio(BaseOptions(baseUrl: baseUrl));

  String get baseUrl => _dio.options.baseUrl;
  final Dio _dio;
  String? _token;
  Map<String, dynamic>? _currentUser;

  bool get isAuthenticated => _token != null && _token!.isNotEmpty;
  bool get isAdmin => _currentUser?['is_admin'] == true;
  Map<String, dynamic>? get currentUser => _currentUser;

  Future<void> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
    final userStr = prefs.getString('current_user');
    if (userStr != null) {
      _currentUser = jsonDecode(userStr) as Map<String, dynamic>;
    }
    if (_token != null) {
      _dio.options.headers['Authorization'] = 'Bearer $_token';
    }
  }

  Future<void> setBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_base_url', url);
    _dio.options.baseUrl = url;
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final resp = await _dio.post('/auth/login', data: {'email': email, 'password': password});
    _token = resp.data['access_token'] as String;
    _dio.options.headers['Authorization'] = 'Bearer $_token';
    _currentUser = resp.data['user'] as Map<String, dynamic>?;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', _token!);
    await prefs.setString('current_user', jsonEncode(_currentUser));
    return resp.data as Map<String, dynamic>;
  }

  Future<void> logout() async {
    _token = null;
    _currentUser = null;
    _dio.options.headers.remove('Authorization');
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('current_user');
  }

  Future<Map<String, dynamic>> uploadMeeting({
    required File file,
    String? title,
    void Function(int sent, int total)? onProgress,
  }) async {
    final formData = FormData.fromMap({
      'file': await MultipartFile.fromFile(file.path, filename: file.path.split(Platform.pathSeparator).last),
      if (title != null) 'title': title,
    });
    final resp = await _dio.post(
      '/meetings/upload',
      data: formData,
      onSendProgress: onProgress,
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<List<dynamic>> listMeetings() async {
    final resp = await _dio.get('/meetings');
    return resp.data as List<dynamic>;
  }

  Future<Map<String, dynamic>> getTranscript(int meetingId) async {
    final resp = await _dio.get('/meetings/$meetingId/transcript');
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> extractTasks(int meetingId) async {
    final resp = await _dio.post('/meetings/$meetingId/extract-tasks');
    return resp.data as Map<String, dynamic>;
  }

  Future<List<dynamic>> listMeetingTasks(int meetingId) async {
    final resp = await _dio.get('/meetings/$meetingId/tasks');
    return resp.data as List<dynamic>;
  }

  // ==================== 声纹相关 API ====================

  Future<List<dynamic>> listEmployees() async {
    final resp = await _dio.get('/employees');
    return resp.data as List<dynamic>;
  }

  Future<Map<String, dynamic>> registerVoicePrint({
    required int employeeId,
    required String audioBase64,
    String? note,
    void Function(int sent, int total)? onProgress,
  }) async {
    final resp = await _dio.post(
      '/voiceprints/register-audio-base64',
      data: {
        'employee_id': employeeId,
        'audio_base64': audioBase64,
        if (note != null) 'note': note,
      },
      onSendProgress: onProgress,
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> registerVoicePrintFromFile({
    required File file,
    required int employeeId,
    String? note,
    void Function(int sent, int total)? onProgress,
  }) async {
    final formData = FormData.fromMap({
      'file': await MultipartFile.fromFile(
        file.path,
        filename: file.path.split(Platform.pathSeparator).last,
      ),
      'employee_id': employeeId,
      if (note != null) 'note': note,
    });
    final resp = await _dio.post(
      '/voiceprints',
      data: formData,
      onSendProgress: onProgress,
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<List<dynamic>> getEmployeeVoicePrints(int employeeId) async {
    final resp = await _dio.get('/voiceprints/employee/$employeeId');
    return resp.data as List<dynamic>;
  }

  Future<Map<String, dynamic>> verifyVoicePrint(int voicePrintId, bool isVerified) async {
    final resp = await _dio.post(
      '/voiceprints/$voicePrintId/verify',
      queryParameters: {'is_verified': isVerified},
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<void> deleteVoicePrint(int voicePrintId) async {
    await _dio.delete('/voiceprints/$voicePrintId');
  }

  // ==================== 消息相关 API ====================

  Future<Map<String, dynamic>> getMessages({
    bool unreadOnly = false,
    int limit = 50,
    int offset = 0,
  }) async {
    final resp = await _dio.get(
      '/messages',
      queryParameters: {
        'unread_only': unreadOnly,
        'limit': limit,
        'offset': offset,
      },
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<int> getUnreadCount() async {
    final resp = await _dio.get('/messages/unread-count');
    return resp.data['unread_count'] as int? ?? 0;
  }

  Future<Map<String, dynamic>> getMessage(int messageId) async {
    final resp = await _dio.get('/messages/$messageId');
    return resp.data as Map<String, dynamic>;
  }

  Future<void> markMessageRead(int messageId) async {
    await _dio.post('/messages/$messageId/read');
  }

  Future<void> markAllMessagesRead() async {
    await _dio.post('/messages/read-all');
  }

  // ==================== 任务相关 API ====================

  Future<Map<String, dynamic>> getTasks({
    String? status,
    int? executorId,
    int limit = 50,
    int offset = 0,
  }) async {
    final resp = await _dio.get(
      '/tasks',
      queryParameters: {
        if (status != null) 'status': status,
        if (executorId != null) 'executor_id': executorId,
        'limit': limit,
        'offset': offset,
      },
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getTask(int taskId) async {
    final resp = await _dio.get('/tasks/$taskId');
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> replyToTask({
    required int taskId,
    required String action,
    String? reason,
  }) async {
    final resp = await _dio.post(
      '/tasks/$taskId/reply',
      data: {
        'action': action,
        if (reason != null) 'reason': reason,
      },
    );
    return resp.data as Map<String, dynamic>;
  }

  // ==================== 员工管理 API ====================

  Future<List<dynamic>> getAllEmployees() async {
    final resp = await _dio.get('/employees');
    return resp.data as List<dynamic>;
  }

  Future<Map<String, dynamic>> getEmployee(int employeeId) async {
    final resp = await _dio.get('/employees/$employeeId');
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createEmployee({
    required String name,
    required String email,
    required String password,
    int? managerId,
  }) async {
    final resp = await _dio.post(
      '/employees',
      data: {
        'name': name,
        'email': email,
        'password': password,
        if (managerId != null) 'manager_id': managerId,
      },
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateEmployee({
    required int employeeId,
    String? name,
    String? email,
    int? managerId,
    bool? isActive,
  }) async {
    final resp = await _dio.put(
      '/employees/$employeeId',
      data: {
        if (name != null) 'name': name,
        if (email != null) 'email': email,
        if (managerId != null) 'manager_id': managerId,
        if (isActive != null) 'is_active': isActive,
      },
    );
    return resp.data as Map<String, dynamic>;
  }

  Future<void> deleteEmployee(int employeeId) async {
    await _dio.delete('/employees/$employeeId');
  }

  Future<List<dynamic>> getSubordinates(int employeeId) async {
    final resp = await _dio.get('/employees/$employeeId/subordinates');
    return resp.data as List<dynamic>;
  }
}
