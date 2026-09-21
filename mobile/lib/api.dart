import 'dart:convert';
import 'package:http/http.dart' as http;

class EarickAPI {
  static const String baseUrl = "https://earick.onrender.com";

  /// Send a message to Earick. Returns the reply and sources.
  static Future<Map<String, dynamic>> chat({
    required String message,
    required List<Map<String, String>> history,
  }) async {
    final uri = Uri.parse("$baseUrl/chat");
    final body = jsonEncode({
      "message": message,
      "mode": "reasoned",
      "history": history,
    });
    try {
      final resp = await http
          .post(
            uri,
            headers: {"Content-Type": "application/json"},
            body: body,
          )
          .timeout(const Duration(seconds: 120));
      if (resp.statusCode != 200) {
        return {"reply": "Error: HTTP ${resp.statusCode}", "sources": []};
      }
      return jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (e) {
      return {"reply": "Network error: $e", "sources": []};
    }
  }

  /// Health check.
  static Future<Map<String, dynamic>> health() async {
    final resp = await http
        .get(Uri.parse("$baseUrl/health"))
        .timeout(const Duration(seconds: 15));
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }
}
