import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'screens/login_screen.dart';
import 'screens/home_screen.dart';
import 'services/api_service.dart';
import 'services/upload_queue.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final apiBaseUrl = prefs.getString('api_base_url') ?? 'http://192.168.10.8:8000';
  final api = ApiService(baseUrl: apiBaseUrl);
  await api.loadToken();
  final uploadQueue = UploadQueue(api: api);
  await uploadQueue.init();
  uploadQueue.startBackgroundProcessor();

  runApp(TaskFlowApp(api: api, uploadQueue: uploadQueue));
}

class TaskFlowApp extends StatefulWidget {
  const TaskFlowApp({super.key, required this.api, required this.uploadQueue});

  final ApiService api;
  final UploadQueue uploadQueue;

  @override
  State<TaskFlowApp> createState() => _TaskFlowAppState();
}

class _TaskFlowAppState extends State<TaskFlowApp> {
  void _refreshAuth() => setState(() {});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TaskFlow',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1565C0)),
        useMaterial3: true,
      ),
      home: widget.api.isAuthenticated
          ? HomeScreen(
              api: widget.api,
              uploadQueue: widget.uploadQueue,
              onLogout: () async {
                await widget.api.logout();
                _refreshAuth();
              },
            )
          : LoginScreen(
              api: widget.api,
              uploadQueue: widget.uploadQueue,
              onLoginSuccess: _refreshAuth,
            ),
    );
  }
}
