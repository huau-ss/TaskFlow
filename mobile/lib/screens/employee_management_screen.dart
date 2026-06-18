import 'package:flutter/material.dart';

import '../services/api_service.dart';

class EmployeeManagementScreen extends StatefulWidget {
  const EmployeeManagementScreen({
    super.key,
    required this.api,
  });

  final ApiService api;

  @override
  State<EmployeeManagementScreen> createState() => _EmployeeManagementScreenState();
}

class _EmployeeManagementScreenState extends State<EmployeeManagementScreen> {
  List<dynamic> _employees = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    setState(() => _loading = true);
    try {
      _employees = await widget.api.getAllEmployees();
    } catch (_) {
      _employees = [];
    }
    if (mounted) setState(() => _loading = false);
  }

  // 构建组织树结构
  List<dynamic> _getRootEmployees() {
    return _employees.where((e) => e['manager_id'] == null).toList();
  }

  List<dynamic> _getSubordinates(int managerId) {
    return _employees.where((e) => e['manager_id'] == managerId).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF0F2F5),
      appBar: AppBar(
        title: const Text('员工管理'),
        backgroundColor: Colors.white,
        foregroundColor: const Color(0xFF1F2329),
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadEmployees,
          ),
          IconButton(
            icon: const Icon(Icons.person_add),
            onPressed: () => _showAddEmployeeDialog(),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _employees.isEmpty
              ? _buildEmptyState()
              : RefreshIndicator(
                  onRefresh: _loadEmployees,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _buildOrgChart(),
                    ],
                  ),
                ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.people_outline, size: 80, color: Colors.grey[300]),
          const SizedBox(height: 16),
          Text(
            '暂无员工',
            style: TextStyle(fontSize: 16, color: Colors.grey[500]),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => _showAddEmployeeDialog(),
            icon: const Icon(Icons.person_add),
            label: const Text('添加员工'),
          ),
        ],
      ),
    );
  }

  Widget _buildOrgChart() {
    final roots = _getRootEmployees();

    if (roots.isEmpty) {
      return _buildNoOrgState();
    }

    return Column(
      children: roots.map((emp) => _buildOrgNode(emp, 0)).toList(),
    );
  }

  Widget _buildNoOrgState() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          Icon(Icons.account_tree_outlined, size: 60, color: Colors.grey[300]),
          const SizedBox(height: 16),
          const Text(
            '暂无组织架构',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: Color(0xFF1F2329),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '请先添加员工并设置上下级关系',
            style: TextStyle(fontSize: 14, color: Colors.grey[500]),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => _showAddEmployeeDialog(),
            icon: const Icon(Icons.person_add),
            label: const Text('添加员工'),
          ),
        ],
      ),
    );
  }

  Widget _buildOrgNode(dynamic employee, int level) {
    final subordinates = _getSubordinates(employee['id'] as int);
    final hasSubordinates = subordinates.isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          margin: EdgeInsets.only(left: level * 20.0),
          child: _buildEmployeeCard(employee, level, hasSubordinates),
        ),
        if (hasSubordinates)
          ...subordinates.map((sub) => _buildOrgNode(sub, level + 1)),
      ],
    );
  }

  Widget _buildEmployeeCard(dynamic employee, int level, bool hasSubordinates) {
    final managerId = employee['manager_id'] as int?;
    final manager = managerId != null
        ? _employees.where((e) => e['id'] == managerId).firstOrNull
        : null;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border(
          left: BorderSide(
            color: _getAvatarColor(employee['name'] as String? ?? ''),
            width: 4,
          ),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 2,
            offset: const Offset(0, 1),
          ),
        ],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => _showEmployeeDetail(employee),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                _buildAvatar(employee['name'] as String? ?? '?'),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        employee['name'] as String? ?? '未知',
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF1F2329),
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        employee['email'] as String? ?? '',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFF8F959E),
                        ),
                      ),
                      if (manager != null) ...[
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            const Icon(
                              Icons.person_outline,
                              size: 12,
                              color: Color(0xFF8F959E),
                            ),
                            const SizedBox(width: 4),
                            Text(
                              '上级: ${manager['name']}',
                              style: const TextStyle(
                                fontSize: 11,
                                color: Color(0xFF8F959E),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
                if (hasSubordinates)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1D74F5).withOpacity(0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.people,
                          size: 12,
                          color: Color(0xFF1D74F5),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          '${_getSubordinates(employee['id'] as int).length}',
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF1D74F5),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(width: 8),
                const Icon(
                  Icons.chevron_right,
                  color: Color(0xFF8F959E),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAvatar(String name) {
    final color = _getAvatarColor(name);
    return Container(
      width: 44,
      height: 44,
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Center(
        child: Text(
          name.isNotEmpty ? name[0].toUpperCase() : '?',
          style: TextStyle(
            color: color,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
    );
  }

  Color _getAvatarColor(String name) {
    final colors = [
      const Color(0xFF1D74F5),
      const Color(0xFF0D8A4E),
      const Color(0xFFB8860B),
      const Color(0xFF7C3AED),
      const Color(0xFFF5455C),
      const Color(0xFF2DE0A5),
    ];
    return colors[name.hashCode.abs() % colors.length];
  }

  void _showEmployeeDetail(dynamic employee) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _EmployeeDetailSheet(
        employee: employee,
        employees: _employees,
        api: widget.api,
        onUpdate: _loadEmployees,
      ),
    );
  }

  void _showAddEmployeeDialog() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _AddEmployeeSheet(
        employees: _employees,
        api: widget.api,
        onAdd: (newEmployee) {
          _loadEmployees();
        },
      ),
    );
  }
}

class _EmployeeDetailSheet extends StatefulWidget {
  final dynamic employee;
  final List<dynamic> employees;
  final ApiService api;
  final VoidCallback onUpdate;

  const _EmployeeDetailSheet({
    required this.employee,
    required this.employees,
    required this.api,
    required this.onUpdate,
  });

  @override
  State<_EmployeeDetailSheet> createState() => _EmployeeDetailSheetState();
}

class _EmployeeDetailSheetState extends State<_EmployeeDetailSheet> {
  late TextEditingController _nameController;
  late TextEditingController _emailController;
  int? _selectedManagerId;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.employee['name'] as String?);
    _emailController = TextEditingController(text: widget.employee['email'] as String?);
    _selectedManagerId = widget.employee['manager_id'] as int?;
  }

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    super.dispose();
  }

  List<dynamic> get _availableManagers {
    return widget.employees
        .where((e) => e['id'] != widget.employee['id'])
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final subordinates = widget.employees
        .where((e) => e['manager_id'] == widget.employee['id'])
        .toList();

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 32,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              '编辑员工',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF1F2329),
              ),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _nameController,
              decoration: InputDecoration(
                labelText: '姓名',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _emailController,
              decoration: InputDecoration(
                labelText: '邮箱',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<int?>(
              value: _selectedManagerId,
              decoration: InputDecoration(
                labelText: '上级',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
              items: [
                const DropdownMenuItem<int?>(
                  value: null,
                  child: Text('无上级（顶级）'),
                ),
                ..._availableManagers.map((e) => DropdownMenuItem<int?>(
                      value: e['id'] as int,
                      child: Text(e['name'] as String? ?? '未知'),
                    )),
              ],
              onChanged: (value) => setState(() => _selectedManagerId = value),
            ),
            if (subordinates.isNotEmpty) ...[
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFF0F2F5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '下属 (${subordinates.length}人)',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF8F959E),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: subordinates
                          .map((e) => Chip(
                                label: Text(e['name'] as String? ?? '未知'),
                                backgroundColor: const Color(0xFF1D74F5).withOpacity(0.1),
                                labelStyle: const TextStyle(
                                  fontSize: 12,
                                  color: Color(0xFF1D74F5),
                                ),
                              ))
                          .toList(),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('取消'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  flex: 2,
                  child: FilledButton(
                    onPressed: _loading ? null : _saveChanges,
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: _loading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Text('保存'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _saveChanges() async {
    if (_nameController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入姓名')),
      );
      return;
    }

    setState(() => _loading = true);
    try {
      await widget.api.updateEmployee(
        employeeId: widget.employee['id'] as int,
        name: _nameController.text.trim(),
        email: _emailController.text.trim(),
        managerId: _selectedManagerId,
      );
      if (mounted) {
        Navigator.pop(context);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('保存成功')),
        );
        widget.onUpdate();
      }
    } catch (e) {
      if (mounted) {
        String message = '保存失败';
        if (e.toString().contains('403')) {
          message = '无权限：需要管理员权限';
        } else if (e.toString().contains('409')) {
          message = '保存失败：邮箱已被使用';
        } else if (e.toString().contains('400')) {
          if (e.toString().contains('Circular')) {
            message = '保存失败：不能形成循环上下级关系';
          } else if (e.toString().contains('subordinates')) {
            message = '保存失败：该员工有下属员工';
          } else {
            message = '保存失败：$e';
          }
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    }
    if (mounted) setState(() => _loading = false);
  }
}

class _AddEmployeeSheet extends StatefulWidget {
  final List<dynamic> employees;
  final ApiService api;
  final Function(dynamic) onAdd;

  const _AddEmployeeSheet({
    required this.employees,
    required this.api,
    required this.onAdd,
  });

  @override
  State<_AddEmployeeSheet> createState() => _AddEmployeeSheetState();
}

class _AddEmployeeSheetState extends State<_AddEmployeeSheet> {
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController(text: 'demo123');
  int? _selectedManagerId;
  bool _loading = false;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 32,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              '添加员工',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF1F2329),
              ),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _nameController,
              decoration: InputDecoration(
                labelText: '姓名 *',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _emailController,
              decoration: InputDecoration(
                labelText: '邮箱 *',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _passwordController,
              decoration: InputDecoration(
                labelText: '初始密码 *',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<int?>(
              value: _selectedManagerId,
              decoration: InputDecoration(
                labelText: '上级',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
              items: [
                const DropdownMenuItem<int?>(
                  value: null,
                  child: Text('无上级（顶级）'),
                ),
                ...widget.employees.map((e) => DropdownMenuItem<int?>(
                      value: e['id'] as int,
                      child: Text(e['name'] as String? ?? '未知'),
                    )),
              ],
              onChanged: (value) => setState(() => _selectedManagerId = value),
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('取消'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  flex: 2,
                  child: FilledButton(
                    onPressed: _loading ? null : _addEmployee,
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: _loading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Text('添加'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _addEmployee() async {
    if (_nameController.text.trim().isEmpty || _emailController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请填写必填项')),
      );
      return;
    }

    setState(() => _loading = true);
    try {
      final result = await widget.api.createEmployee(
        name: _nameController.text.trim(),
        email: _emailController.text.trim(),
        password: _passwordController.text,
        managerId: _selectedManagerId,
      );
      if (mounted) {
        Navigator.pop(context);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('添加成功')),
        );
        widget.onAdd(result);
      }
    } catch (e) {
      if (mounted) {
        String message = '添加失败';
        if (e.toString().contains('403')) {
          message = '无权限：需要管理员权限';
        } else if (e.toString().contains('409')) {
          message = '添加失败：邮箱已被使用';
        } else if (e.toString().contains('400')) {
          if (e.toString().contains('Circular')) {
            message = '添加失败：不能形成循环上下级关系';
          } else if (e.toString().contains('subordinates')) {
            message = '添加失败：该员工有下属员工';
          } else {
            message = '添加失败：$e';
          }
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    }
    if (mounted) setState(() => _loading = false);
  }
}
