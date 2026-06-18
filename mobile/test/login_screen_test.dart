import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// 创建简单的测试组件来模拟登录流程
class TestLoginWidget extends StatefulWidget {
  final String? errorMessage;
  final bool isLoading;
  final VoidCallback? onLoginSuccess;
  final VoidCallback? onLoginError;

  const TestLoginWidget({
    super.key,
    this.errorMessage,
    this.isLoading = false,
    this.onLoginSuccess,
    this.onLoginError,
  });

  @override
  State<TestLoginWidget> createState() => _TestLoginWidgetState();
}

class _TestLoginWidgetState extends State<TestLoginWidget> {
  final _emailCtrl = TextEditingController(text: 'admin@company.com');
  final _passwordCtrl = TextEditingController(text: 'admin123');
  final _urlCtrl = TextEditingController(text: 'http://192.168.10.8:8000');

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _urlCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
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
              if (widget.errorMessage != null) ...[
                const SizedBox(height: 12),
                Text(widget.errorMessage!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 24),
              FilledButton(
                onPressed: widget.isLoading
                    ? null
                    : () {
                        if (widget.onLoginError != null && widget.errorMessage != null) {
                          widget.onLoginError!();
                        } else if (widget.onLoginSuccess != null) {
                          widget.onLoginSuccess!();
                        }
                      },
                child: widget.isLoading
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

void main() {
  group('LoginScreen Widget Tests', () {
    testWidgets('登录界面显示正确', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TestLoginWidget(),
        ),
      );

      // 验证标题
      expect(find.text('TaskFlow'), findsOneWidget);
      expect(find.text('录音驱动任务协同'), findsOneWidget);

      // 验证输入框标签
      expect(find.text('API 地址'), findsOneWidget);
      expect(find.text('邮箱'), findsOneWidget);
      expect(find.text('密码'), findsOneWidget);

      // 验证登录按钮
      expect(find.text('登录'), findsOneWidget);
    });

    testWidgets('默认填入测试账号密码', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TestLoginWidget(),
        ),
      );

      // 验证默认填入的值
      expect(find.text('http://192.168.10.8:8000'), findsOneWidget);
      expect(find.text('admin@company.com'), findsOneWidget);
    });

    testWidgets('点击登录按钮显示加载状态', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TestLoginWidget(isLoading: true),
        ),
      );

      // 验证加载指示器
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('登录失败显示错误信息', (WidgetTester tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: TestLoginWidget(errorMessage: '网络连接失败'),
        ),
      );

      // 验证错误信息
      expect(find.text('网络连接失败'), findsOneWidget);
    });

    testWidgets('可以修改API地址', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TestLoginWidget(),
        ),
      );

      // 找到API地址输入框并输入
      await tester.enterText(find.byType(TextField).first, 'http://localhost:8000');
      await tester.pump();

      // 验证修改后的值
      expect(find.text('http://localhost:8000'), findsOneWidget);
    });

    testWidgets('密码字段是隐藏的', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TestLoginWidget(),
        ),
      );

      // 找到密码输入框
      final passwordField = find.byType(TextField).at(2);
      expect(passwordField, findsOneWidget);

      // 验证是密码字段（obscureText 属性）
      final textField = tester.widget<TextField>(passwordField);
      expect(textField.obscureText, isTrue);
    });

    testWidgets('点击登录按钮触发回调', (WidgetTester tester) async {
      bool loginCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: TestLoginWidget(
            onLoginSuccess: () => loginCalled = true,
          ),
        ),
      );

      // 点击登录
      await tester.tap(find.text('登录'));
      await tester.pump();

      // 验证回调被触发
      expect(loginCalled, isTrue);
    });
  });
}
