import 'package:flutter/material.dart';
import '../services/api_service.dart';

class MeScreen extends StatelessWidget {
  const MeScreen({super.key, required this.api});

  final ApiService api;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: ListTile(
            leading: const CircleAvatar(child: Icon(Icons.person)),
            title: const Text('个人中心'),
            subtitle: const Text('查看账户信息'),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.info_outline),
                title: const Text('版本'),
                trailing: const Text('0.1.0'),
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
