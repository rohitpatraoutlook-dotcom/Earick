import 'package:flutter/material.dart';
import 'chat_screen.dart';

void main() {
  runApp(const EarickApp());
}

class EarickApp extends StatelessWidget {
  const EarickApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Earick',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.light,
        scaffoldBackgroundColor: const Color(0xFFFFFFFF),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1A1A1A),
          brightness: Brightness.light,
        ),
        fontFamily: 'Roboto',
        useMaterial3: true,
      ),
      home: const ChatScreen(),
    );
  }
}
