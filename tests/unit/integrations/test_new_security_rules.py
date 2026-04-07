"""Tests for the 30 new OWASP Top 10 security anti-pattern rules.

Validates that each new rule correctly matches dangerous code patterns
while avoiding false positives on safe code.
"""

from __future__ import annotations

from attocode.integrations.security.matcher import iter_pattern_matches
from attocode.integrations.security.patterns import ANTI_PATTERNS


def _get_pattern(name: str):
    """Get a pattern by name from ANTI_PATTERNS."""
    return next(p for p in ANTI_PATTERNS if p.name == name)


# -------------------------------------------------------------------------
# Python OWASP rules
# -------------------------------------------------------------------------


class TestPythonOWASPRules:
    """Test Python-specific OWASP Top 10 anti-pattern rules."""

    # --- python_sql_format_string ---

    def test_python_sql_format_string_matches_percent_s(self):
        pat = _get_pattern("python_sql_format_string")
        code = '''cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_sql_format_string_matches_percent_d(self):
        pat = _get_pattern("python_sql_format_string")
        code = '''cursor.execute("DELETE FROM orders WHERE order_id = %d" % oid)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_sql_format_string_safe_parameterized(self):
        pat = _get_pattern("python_sql_format_string")
        code = '''cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_sql_concat ---

    def test_python_sql_concat_matches(self):
        pat = _get_pattern("python_sql_concat")
        code = '''cursor.execute("SELECT * FROM users WHERE id = " + user_id)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_sql_concat_safe_parameterized(self):
        pat = _get_pattern("python_sql_concat")
        code = '''cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_marshal_loads ---

    def test_python_marshal_loads_matches_loads(self):
        pat = _get_pattern("python_marshal_loads")
        code = '''data = marshal.loads(raw_bytes)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_marshal_loads_matches_load(self):
        pat = _get_pattern("python_marshal_loads")
        code = '''obj = marshal.load(f)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_marshal_loads_safe_json(self):
        pat = _get_pattern("python_marshal_loads")
        code = '''data = json.loads(raw_bytes)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_debug_true ---

    def test_python_debug_true_matches(self):
        pat = _get_pattern("python_debug_true")
        code = '''DEBUG = True'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_debug_true_safe_false(self):
        pat = _get_pattern("python_debug_true")
        code = '''DEBUG = False'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    def test_python_debug_true_safe_env(self):
        pat = _get_pattern("python_debug_true")
        code = '''DEBUG = os.environ.get("DEBUG", "false")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_assert_security ---

    def test_python_assert_security_matches(self):
        pat = _get_pattern("python_assert_security")
        code = '''assert user.is_authenticated'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_assert_security_safe_in_test(self):
        pat = _get_pattern("python_assert_security")
        code = '''assert result == expected  # test assertion'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    def test_python_assert_security_safe_in_spec(self):
        pat = _get_pattern("python_assert_security")
        code = '''assert value > 0  # spec check'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_os_system ---

    def test_python_os_system_matches(self):
        pat = _get_pattern("python_os_system")
        code = '''os.system("rm -rf " + user_input)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_os_system_safe_subprocess(self):
        pat = _get_pattern("python_os_system")
        code = '''subprocess.run(["rm", "-rf", path], check=True)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_popen ---

    def test_python_popen_matches(self):
        pat = _get_pattern("python_popen")
        code = '''f = os.popen("ls " + directory)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_popen_safe_subprocess(self):
        pat = _get_pattern("python_popen")
        code = '''result = subprocess.run(["ls", directory], capture_output=True)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_ssrf_request ---

    def test_python_ssrf_request_fstring(self):
        pat = _get_pattern("python_ssrf_request")
        code = '''requests.get(f"http://api.example.com/{user_input}")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_ssrf_request_concat(self):
        pat = _get_pattern("python_ssrf_request")
        # The regex detects concat when the variable comes before string parts
        code = '''requests.post(base_url + "/endpoint")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_ssrf_request_format(self):
        pat = _get_pattern("python_ssrf_request")
        code = '''requests.get("http://api.example.com/{}".format(user_input))'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_ssrf_request_safe_static(self):
        pat = _get_pattern("python_ssrf_request")
        code = '''requests.get("http://api.example.com/users")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_path_traversal ---

    def test_python_path_traversal_matches_request(self):
        pat = _get_pattern("python_path_traversal")
        code = '''f = open(os.path.join(base_dir, request.args["file"]))'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_path_traversal_matches_params(self):
        pat = _get_pattern("python_path_traversal")
        code = '''f = open(params["filename"])'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_path_traversal_safe_static(self):
        pat = _get_pattern("python_path_traversal")
        code = '''f = open("config.json")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_weak_random ---

    def test_python_weak_random_matches_random(self):
        pat = _get_pattern("python_weak_random")
        code = '''token = random.random()'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_weak_random_matches_randint(self):
        pat = _get_pattern("python_weak_random")
        code = '''otp = random.randint(100000, 999999)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_weak_random_matches_choice(self):
        pat = _get_pattern("python_weak_random")
        code = '''char = random.choice(alphabet)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_weak_random_safe_secrets(self):
        pat = _get_pattern("python_weak_random")
        code = '''token = secrets.token_hex(32)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_cors_wildcard ---

    def test_python_cors_wildcard_matches(self):
        pat = _get_pattern("python_cors_wildcard")
        code = '''CORS(app, origins="*")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_cors_wildcard_matches_config(self):
        pat = _get_pattern("python_cors_wildcard")
        code = '''cors_origins = "*"'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_python_cors_wildcard_safe_specific(self):
        pat = _get_pattern("python_cors_wildcard")
        code = '''ALLOWED_ORIGINS = ["https://example.com"]'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- hardcoded_ip_address ---

    def test_hardcoded_ip_address_matches(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = '''server = "192.168.1.100"'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_hardcoded_ip_address_matches_single_quotes(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = """host = '10.0.0.1'"""
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_hardcoded_ip_address_safe_variable(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = '''server = os.environ["SERVER_IP"]'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0


# -------------------------------------------------------------------------
# JavaScript / TypeScript OWASP rules
# -------------------------------------------------------------------------


class TestJavaScriptOWASPRules:
    """Test JavaScript/TypeScript-specific OWASP Top 10 anti-pattern rules."""

    # --- js_no_escape_html ---

    def test_js_no_escape_html_matches_variable(self):
        pat = _get_pattern("js_no_escape_html")
        code = '''$('#content').html(userInput)'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_no_escape_html_safe_static_string(self):
        pat = _get_pattern("js_no_escape_html")
        code = '''$('#content').html('<b>Hello</b>')'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    def test_js_no_escape_html_safe_text(self):
        pat = _get_pattern("js_no_escape_html")
        code = '''$('#content').text(userInput)'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_url_redirect ---

    def test_js_url_redirect_matches_window_location(self):
        pat = _get_pattern("js_url_redirect")
        code = '''window.location = userInput;'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_url_redirect_matches_location_href(self):
        pat = _get_pattern("js_url_redirect")
        code = '''location.href = params.redirect;'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_url_redirect_safe_no_assignment(self):
        pat = _get_pattern("js_url_redirect")
        # Safe: reading location, not assigning to it
        code = '''const url = window.location.href;'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_postmessage_wildcard ---

    def test_js_postmessage_wildcard_matches(self):
        pat = _get_pattern("js_postmessage_wildcard")
        code = '''iframe.contentWindow.postMessage(data, "*")'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_postmessage_wildcard_matches_single_quotes(self):
        pat = _get_pattern("js_postmessage_wildcard")
        code = """window.postMessage(data, '*')"""
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_postmessage_wildcard_safe_specific_origin(self):
        pat = _get_pattern("js_postmessage_wildcard")
        code = '''iframe.contentWindow.postMessage(data, "https://example.com")'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_unsafe_regex ---

    def test_js_unsafe_regex_matches_variable(self):
        pat = _get_pattern("js_unsafe_regex")
        code = '''const re = new RegExp(userInput);'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_unsafe_regex_safe_string_literal(self):
        pat = _get_pattern("js_unsafe_regex")
        code = '''const re = new RegExp("^[a-z]+$");'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_prototype_pollution ---

    def test_js_prototype_pollution_matches_proto(self):
        pat = _get_pattern("js_prototype_pollution")
        code = '''obj.__proto__["isAdmin"] = true;'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_prototype_pollution_matches_constructor_prototype(self):
        pat = _get_pattern("js_prototype_pollution")
        code = '''obj.constructor.prototype["admin"] = true;'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_prototype_pollution_safe_object_create(self):
        pat = _get_pattern("js_prototype_pollution")
        code = '''const safe = Object.create(null);'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_child_process_exec ---

    def test_js_child_process_exec_matches_variable(self):
        pat = _get_pattern("js_child_process_exec")
        # The pattern matches exec( followed by a non-quote character
        code = '''exec(userCommand, callback);'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_child_process_exec_safe_string_literal(self):
        pat = _get_pattern("js_child_process_exec")
        code = '''exec("ls -la", callback);'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- js_nosql_injection ---

    def test_js_nosql_injection_matches_gt(self):
        pat = _get_pattern("js_nosql_injection")
        code = '''db.users.find({ age: { $gt: userAge } });'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_nosql_injection_matches_where(self):
        pat = _get_pattern("js_nosql_injection")
        code = '''db.users.find({ $where: userFunc });'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_nosql_injection_matches_ne(self):
        pat = _get_pattern("js_nosql_injection")
        code = '''db.users.find({ password: { $ne: "" } });'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_js_nosql_injection_safe_plain_query(self):
        pat = _get_pattern("js_nosql_injection")
        code = '''db.users.find({ name: "Alice" });'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) == 0

    # --- Language filtering ---

    def test_js_rules_do_not_match_python(self):
        pat = _get_pattern("js_url_redirect")
        code = '''window.location = userInput;'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    def test_js_rules_match_typescript(self):
        pat = _get_pattern("js_prototype_pollution")
        code = '''obj.__proto__["isAdmin"] = true;'''
        matches = list(iter_pattern_matches(code, [pat], "typescript"))
        assert len(matches) >= 1


# -------------------------------------------------------------------------
# Go OWASP rules
# -------------------------------------------------------------------------


class TestGoOWASPRules:
    """Test Go-specific OWASP Top 10 anti-pattern rules."""

    # --- go_sql_sprintf ---

    def test_go_sql_sprintf_matches_select(self):
        pat = _get_pattern("go_sql_sprintf")
        code = '''query := fmt.Sprintf("SELECT * FROM users WHERE id = %s", id)'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_go_sql_sprintf_matches_delete(self):
        pat = _get_pattern("go_sql_sprintf")
        code = '''q := fmt.Sprintf("DELETE FROM sessions WHERE user_id = %d", uid)'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_go_sql_sprintf_safe_parameterized(self):
        pat = _get_pattern("go_sql_sprintf")
        code = '''rows, err := db.Query("SELECT * FROM users WHERE id = $1", id)'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) == 0

    def test_go_sql_sprintf_safe_non_sql_sprintf(self):
        pat = _get_pattern("go_sql_sprintf")
        code = '''msg := fmt.Sprintf("Hello, %s!", name)'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) == 0

    # --- go_unhandled_error ---

    def test_go_unhandled_error_matches(self):
        pat = _get_pattern("go_unhandled_error")
        code = '''_ = db.Close()'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_go_unhandled_error_matches_second_return(self):
        pat = _get_pattern("go_unhandled_error")
        code = '''result, _ = db.Query("SELECT 1")'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_go_unhandled_error_safe_handled(self):
        pat = _get_pattern("go_unhandled_error")
        code = '''err := db.Close()'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) == 0

    # --- go_tls_insecure ---

    def test_go_tls_insecure_matches(self):
        pat = _get_pattern("go_tls_insecure")
        code = '''tls.Config{InsecureSkipVerify: true}'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_go_tls_insecure_safe_false(self):
        pat = _get_pattern("go_tls_insecure")
        code = '''tls.Config{InsecureSkipVerify: false}'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) == 0

    def test_go_tls_insecure_safe_default(self):
        pat = _get_pattern("go_tls_insecure")
        code = '''tls.Config{}'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) == 0

    # --- Language filtering ---

    def test_go_rules_do_not_match_python(self):
        pat = _get_pattern("go_sql_sprintf")
        code = '''query := fmt.Sprintf("SELECT * FROM users WHERE id = %s", id)'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0


# -------------------------------------------------------------------------
# Java / Kotlin OWASP rules
# -------------------------------------------------------------------------


class TestJavaOWASPRules:
    """Test Java/Kotlin-specific OWASP Top 10 anti-pattern rules."""

    # --- java_sql_concat ---

    def test_java_sql_concat_matches(self):
        pat = _get_pattern("java_sql_concat")
        code = '''Statement stmt = conn.createStatement(); stmt.executeQuery(query);'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_sql_concat_safe_parameterized(self):
        pat = _get_pattern("java_sql_concat")
        code = '''PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE id = ?");'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) == 0

    # --- java_xxe ---

    def test_java_xxe_matches_document_builder(self):
        pat = _get_pattern("java_xxe")
        code = '''DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_xxe_matches_sax_parser(self):
        pat = _get_pattern("java_xxe")
        code = '''SAXParserFactory spf = SAXParserFactory.newInstance();'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_xxe_matches_xml_input_factory(self):
        pat = _get_pattern("java_xxe")
        code = '''XMLInputFactory xif = XMLInputFactory.newInstance();'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_xxe_safe_json_parser(self):
        pat = _get_pattern("java_xxe")
        code = '''JsonParser parser = new JsonParser();'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) == 0

    # --- java_deserialization ---

    def test_java_deserialization_matches(self):
        pat = _get_pattern("java_deserialization")
        code = '''ObjectInputStream ois = new ObjectInputStream(inputStream);'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_deserialization_safe_json(self):
        pat = _get_pattern("java_deserialization")
        code = '''ObjectMapper mapper = new ObjectMapper();'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) == 0

    # --- java_weak_crypto ---

    def test_java_weak_crypto_matches_des(self):
        pat = _get_pattern("java_weak_crypto")
        code = '''Cipher cipher = Cipher.getInstance("DES/ECB/PKCS5Padding");'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_weak_crypto_matches_rc4(self):
        pat = _get_pattern("java_weak_crypto")
        code = '''Cipher cipher = Cipher.getInstance("RC4");'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_weak_crypto_matches_blowfish(self):
        pat = _get_pattern("java_weak_crypto")
        code = '''Cipher cipher = Cipher.getInstance("Blowfish");'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) >= 1

    def test_java_weak_crypto_safe_aes(self):
        pat = _get_pattern("java_weak_crypto")
        code = '''Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");'''
        matches = list(iter_pattern_matches(code, [pat], "java"))
        assert len(matches) == 0

    # --- Language filtering ---

    def test_java_rules_match_kotlin(self):
        pat = _get_pattern("java_deserialization")
        code = '''val ois = ObjectInputStream(inputStream)'''
        matches = list(iter_pattern_matches(code, [pat], "kotlin"))
        assert len(matches) >= 1

    def test_java_rules_do_not_match_python(self):
        pat = _get_pattern("java_xxe")
        code = '''DocumentBuilderFactory.newInstance()'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0


# -------------------------------------------------------------------------
# Ruby OWASP rules
# -------------------------------------------------------------------------


class TestRubyOWASPRules:
    """Test Ruby-specific OWASP Top 10 anti-pattern rules."""

    # --- ruby_system_call ---

    def test_ruby_system_call_matches_system(self):
        pat = _get_pattern("ruby_system_call")
        code = '''system(user_input)'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_system_call_matches_exec(self):
        pat = _get_pattern("ruby_system_call")
        # exec with a variable (non-quoted) argument
        code = '''exec(cmd)'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_system_call_matches_spawn(self):
        pat = _get_pattern("ruby_system_call")
        code = '''spawn(command)'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_system_call_matches_io_popen(self):
        pat = _get_pattern("ruby_system_call")
        code = '''IO.popen(cmd)'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_system_call_safe_no_call(self):
        pat = _get_pattern("ruby_system_call")
        # Safe: not a system/exec/spawn/IO.popen call
        code = '''result = run_command(args)'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) == 0

    # --- ruby_send_dynamic ---

    def test_ruby_send_dynamic_matches_params(self):
        pat = _get_pattern("ruby_send_dynamic")
        code = '''obj.send(params[:method])'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_send_dynamic_matches_request(self):
        pat = _get_pattern("ruby_send_dynamic")
        code = '''user.send(request.params["action"])'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) >= 1

    def test_ruby_send_dynamic_safe_static(self):
        pat = _get_pattern("ruby_send_dynamic")
        code = '''obj.send("valid_method")'''
        matches = list(iter_pattern_matches(code, [pat], "ruby"))
        assert len(matches) == 0

    # --- Language filtering ---

    def test_ruby_rules_do_not_match_python(self):
        pat = _get_pattern("ruby_send_dynamic")
        code = '''obj.send(params[:method])'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0


# -------------------------------------------------------------------------
# Multi-language rules
# -------------------------------------------------------------------------


class TestMultiLanguageRules:
    """Test multi-language / language-agnostic anti-pattern rules."""

    # --- hardcoded_ip_address (cross-language) ---

    def test_hardcoded_ip_address_matches_in_javascript(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = '''const host = "192.168.0.1";'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_hardcoded_ip_address_matches_in_go(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = '''host := "10.0.0.5"'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_hardcoded_ip_address_no_match_without_quotes(self):
        pat = _get_pattern("hardcoded_ip_address")
        code = '''version = 1.2.3.4'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- python_cors_wildcard (cross-language since languages=[]) ---

    def test_cors_wildcard_matches_in_javascript(self):
        pat = _get_pattern("python_cors_wildcard")
        code = '''app.use(cors({ origin: "*" }));'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_cors_wildcard_matches_in_go(self):
        pat = _get_pattern("python_cors_wildcard")
        code = '''cors.AllowAll("*")'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    # --- hardcoded_localhost ---

    def test_hardcoded_localhost_matches_localhost(self):
        pat = _get_pattern("hardcoded_localhost")
        code = '''server = "localhost:8080"'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_hardcoded_localhost_matches_127(self):
        pat = _get_pattern("hardcoded_localhost")
        code = '''const url = "127.0.0.1:3000";'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_hardcoded_localhost_matches_0000(self):
        pat = _get_pattern("hardcoded_localhost")
        code = '''bind := "0.0.0.0:8443"'''
        matches = list(iter_pattern_matches(code, [pat], "go"))
        assert len(matches) >= 1

    def test_hardcoded_localhost_safe_env_var(self):
        pat = _get_pattern("hardcoded_localhost")
        code = '''server = os.environ.get("HOST", "")'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    def test_hardcoded_localhost_safe_no_port(self):
        pat = _get_pattern("hardcoded_localhost")
        code = '''host = "localhost"'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    # --- todo_fixme_security ---

    def test_todo_fixme_security_matches_hash_comment(self):
        pat = _get_pattern("todo_fixme_security")
        # scan_comments=True so comment lines are scanned
        code = '''# TODO fix security vulnerability here'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_todo_fixme_security_matches_slash_comment(self):
        pat = _get_pattern("todo_fixme_security")
        code = '''// FIXME: password hashing is insecure'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_todo_fixme_security_matches_hack_token(self):
        pat = _get_pattern("todo_fixme_security")
        code = '''# HACK: token validation bypassed for now'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) >= 1

    def test_todo_fixme_security_matches_xxx_auth(self):
        pat = _get_pattern("todo_fixme_security")
        code = '''// XXX auth check missing'''
        matches = list(iter_pattern_matches(code, [pat], "javascript"))
        assert len(matches) >= 1

    def test_todo_fixme_security_safe_non_security_todo(self):
        pat = _get_pattern("todo_fixme_security")
        code = '''# TODO refactor this function for readability'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0

    def test_todo_fixme_security_safe_regular_comment(self):
        pat = _get_pattern("todo_fixme_security")
        code = '''# This function handles user authentication'''
        matches = list(iter_pattern_matches(code, [pat], "python"))
        assert len(matches) == 0
