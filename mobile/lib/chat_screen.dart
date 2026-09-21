import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'api.dart';

class Message {
  final String role;
  final String content;
  Message({required this.role, required this.content});
  Map<String, String> toJson() => {"role": role, "content": content};
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<Message> _messages = [];
  bool _loading = false;
  String _status = "connecting...";

  @override
  void initState() {
    super.initState();
    _loadState();
    _checkHealth();
  }

  Future<void> _loadState() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('messages');
    if (raw != null) {
      final list = jsonDecode(raw) as List;
      setState(() {
        _messages.clear();
        for (final m in list) {
          _messages.add(Message(role: m['role'], content: m['content']));
        }
      });
    }
  }

  Future<void> _saveState() async {
    final prefs = await SharedPreferences.getInstance();
    final list = _messages.map((m) => m.toJson()).toList();
    await prefs.setString('messages', jsonEncode(list));
  }

  Future<void> _checkHealth() async {
    try {
      final h = await EarickAPI.health();
      setState(() => _status =
          "${h['books'] ?? '?'} books · ${h['chunks'] ?? '?'} chunks");
    } catch (e) {
      setState(() => _status = "offline");
    }
  }

  void _scrollDown() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _loading) return;
    _controller.clear();

    setState(() {
      _messages.add(Message(role: "user", content: text));
      _loading = true;
    });
    _scrollDown();
    _saveState();

    final history = _messages
        .sublist(0, _messages.length - 1)
        .take(8)
        .map((m) => m.toJson())
        .toList();

    final result = await EarickAPI.chat(message: text, history: history);
    final reply = result['reply'] ?? "(no reply)";

    setState(() {
      _messages.add(Message(role: "assistant", content: reply));
      _loading = false;
    });
    _scrollDown();
    _saveState();
  }

  void _clearChat() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Clear this chat?"),
        content: const Text("All messages in this session will be lost."),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              setState(() => _messages.clear());
              _saveState();
            },
            child: const Text("Clear"),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Earick",
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            Text(_status,
                style: const TextStyle(fontSize: 11, color: Colors.grey)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: _clearChat,
            tooltip: "Clear chat",
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
                ? _welcome()
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    itemCount: _messages.length,
                    itemBuilder: (context, i) {
                      final m = _messages[i];
                      return _bubble(m);
                    },
                  ),
          ),
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text("Reasoning…",
                  style: TextStyle(
                      fontStyle: FontStyle.italic, color: Colors.grey)),
            ),
          _inputBar(),
        ],
      ),
    );
  }

  Widget _welcome() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text("⚛️", style: TextStyle(fontSize: 48)),
            const SizedBox(height: 12),
            const Text("Good to see you.",
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            const Text(
              "I'm Earick — a physics and math tutor. Ask me anything.",
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey),
            ),
            const SizedBox(height: 24),
            _suggestion("What is Newton's second law?"),
            _suggestion("Why is entropy always increasing?"),
            _suggestion("Does F = ma apply in string theory?"),
          ],
        ),
      ),
    );
  }

  Widget _suggestion(String s) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: OutlinedButton(
        onPressed: () {
          _controller.text = s;
          _send();
        },
        style: OutlinedButton.styleFrom(
          side: const BorderSide(color: Color(0xFFE5E7EB)),
          foregroundColor: Colors.black87,
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20)),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        ),
        child: Text(s, style: const TextStyle(fontSize: 13)),
      ),
    );
  }

  Widget _bubble(Message m) {
    final isUser = m.role == "user";
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.85,
        ),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFFF3F4F6) : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
        ),
        child: isUser
            ? Text(m.content, style: const TextStyle(fontSize: 14))
            : MarkdownBody(
                data: m.content,
                styleSheet: MarkdownStyleSheet(
                  p: const TextStyle(fontSize: 14, height: 1.5),
                  h1: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                  h2: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  h3: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                  code: const TextStyle(
                      fontFamily: 'monospace',
                      backgroundColor: Color(0xFFF3F4F6),
                      fontSize: 13),
                ),
              ),
      ),
    );
  }

  Widget _inputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Color(0xFFE5E7EB))),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: InputDecoration(
                hintText: "Ask a physics or math question…",
                hintStyle: const TextStyle(color: Colors.grey, fontSize: 13),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(22),
                  borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(22),
                  borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
                ),
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12),
              ),
            ),
          ),
          const SizedBox(width: 8),
          CircleAvatar(
            backgroundColor: _loading ? Colors.grey : Colors.black,
            radius: 22,
            child: IconButton(
              icon: const Icon(Icons.arrow_upward,
                  color: Colors.white, size: 18),
              onPressed: _loading ? null : _send,
            ),
          ),
        ],
      ),
    );
  }
}
