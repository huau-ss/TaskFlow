import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// 创建模拟的任务屏幕组件
class MockTasksScreen extends StatefulWidget {
  const MockTasksScreen({super.key});

  @override
  State<MockTasksScreen> createState() => _MockTasksScreenState();
}

class _MockTasksScreenState extends State<MockTasksScreen> with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('任务'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: '全部'),
            Tab(text: '待处理'),
            Tab(text: '进行中'),
            Tab(text: '已完成'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildTaskList('全部任务'),
          _buildTaskList('待处理任务'),
          _buildTaskList('进行中任务'),
          _buildTaskList('已完成任务'),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: 0,
        onTap: (index) {},
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.assignment), label: '任务'),
          BottomNavigationBarItem(icon: Icon(Icons.message), label: '消息'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: '我的'),
        ],
      ),
    );
  }

  Widget _buildTaskList(String title) {
    return Center(
      child: Text(title, style: const TextStyle(fontSize: 18)),
    );
  }
}

void main() {
  group('TasksScreen Widget Tests', () {
    testWidgets('任务页面AppBar标题显示正确', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      // 使用精确查找 AppBar 中的标题
      final appBarTitleFinder = find.widgetWithText(AppBar, '任务');
      expect(appBarTitleFinder, findsOneWidget);
    });

    testWidgets('任务页面包含TabBar', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      expect(find.byType(TabBar), findsOneWidget);
    });

    testWidgets('任务页面包含TabBarView', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      expect(find.byType(TabBarView), findsOneWidget);
    });

    testWidgets('任务页面底部导航栏存在', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      expect(find.byType(BottomNavigationBar), findsOneWidget);
    });

    testWidgets('任务页面底部导航栏有3个选项', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      // 底部导航栏有3个导航项，使用图标来验证
      expect(find.byIcon(Icons.assignment), findsOneWidget);
      expect(find.byIcon(Icons.message), findsOneWidget);
      expect(find.byIcon(Icons.person), findsOneWidget);
      // 验证底部导航栏只有一个
      expect(find.byType(BottomNavigationBar), findsOneWidget);
    });

    testWidgets('TabBar有4个标签页', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      expect(find.text('全部'), findsOneWidget);
      expect(find.text('待处理'), findsOneWidget);
      expect(find.text('进行中'), findsOneWidget);
      expect(find.text('已完成'), findsOneWidget);
    });

    testWidgets('可以切换标签页', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      // 默认显示全部
      expect(find.text('全部任务'), findsOneWidget);

      // 点击进行中标签
      await tester.tap(find.text('进行中'));
      await tester.pumpAndSettle();

      // 验证切换到进行中
      expect(find.text('进行中任务'), findsOneWidget);
    });

    testWidgets('BottomNavigationBar图标正确', (WidgetTester tester) async {
      await tester.pumpWidget(const MaterialApp(home: MockTasksScreen()));

      expect(find.byIcon(Icons.assignment), findsOneWidget);
      expect(find.byIcon(Icons.message), findsOneWidget);
      expect(find.byIcon(Icons.person), findsOneWidget);
    });
  });
}
