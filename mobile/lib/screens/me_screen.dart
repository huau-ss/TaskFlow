import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'employee_management_screen.dart';

class MeScreen extends StatelessWidget {
  const MeScreen({super.key, required this.api});

  final ApiService api;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const CircleAvatar(child: Icon(Icons.person)),
                title: const Text('个人中心'),
                subtitle: const Text('查看账户信息'),
              ),
              ListTile(
                leading: const Icon(Icons.people, color: Color(0xFF1D74F5)),
                title: const Text('员工管理'),
                subtitle: const Text('配置组织架构和上下级'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => EmployeeManagementScreen(api: api),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.info_outline),
                title: const Text('版本'),
                trailing: const Text('0.2.0'),
              ),
              ListTile(
                leading: const Icon(Icons.cloud_outlined),
                title: const Text('API 地址'),
                subtitle: Text(api.baseUrl),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
