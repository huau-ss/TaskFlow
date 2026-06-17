import 'dart:io';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  ApiService({required String baseUrl}) : _dio = Dio(BaseOptions(baseUrl: baseUrl));

  String get baseUrl => _dio.options.baseUrl;
  final Dio _dio;
  String? _token;

  bool get isAuthenticated => _token != null && _token!.isNotEmpty;

  Future<void> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
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
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', _token!);
    return resp.data as Map<String, dynamic>;
  }

  Future<void> logout() async {
    _token = null;
    _dio.options.headers.remove('Authorization');
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
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
}
