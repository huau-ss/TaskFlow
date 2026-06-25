import 'package:flutter/material.dart';

import '../services/api_service.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.api,
    required this.uploadQueue,
    required this.onLoginSuccess,
  });

  final ApiService api;
  final dynamic uploadQueue;
  final VoidCallback onLoginSuccess;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController(text: 'admin@company.com');
  final _passwordCtrl = TextEditingController(text: 'admin123');
  final _urlCtrl = TextEditingController(text: 'http://localhost:8000');
  bool _loading = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await widget.api.setBaseUrl(_urlCtrl.text.trim());
      await widget.api.login(_emailCtrl.text.trim(), _passwordCtrl.text);
      if (!mounted) return;
      widget.onLoginSuccess();
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 48),
              Text('TaskFlow', style: Theme.of(context).textTheme.headlineLarge),
              const SizedBox(height: 8),
              Text('录音驱动任务协同', style: Theme.of(context).textTheme.bodyLarge),
              const SizedBox(height: 32),
              TextField(
                controller: _urlCtrl,
                decoration: const InputDecoration(labelText: 'API 地址', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _emailCtrl,
                decoration: const InputDecoration(labelText: '邮箱', border: OutlineInputBorder()),
                keyboardType: TextInputType.emailAddress,
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _passwordCtrl,
                decoration: const InputDecoration(labelText: '密码', border: OutlineInputBorder()),
                obscureText: true,
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 24),
              FilledButton(
                onPressed: _loading ? null : _login,
                child: _loading
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('登录'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
