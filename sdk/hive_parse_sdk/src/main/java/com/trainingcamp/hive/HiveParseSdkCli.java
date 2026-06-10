package com.trainingcamp.hive;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.hadoop.hive.ql.parse.ParseDriver;

public final class HiveParseSdkCli {
    private static final Gson GSON = new Gson();
    private static final Pattern LINE_COLUMN_PATTERN =
            Pattern.compile("line\\s+(\\d+)(?:[: ,]+column\\s+|[: ,]+)(\\d+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern POSITION_PATTERN = Pattern.compile("(\\d+):(\\d+)");

    private HiveParseSdkCli() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 4 && "--input-jsonl".equals(args[0]) && "--output-jsonl".equals(args[2])) {
            processJsonl(Path.of(args[1]), Path.of(args[3]));
            return;
        }

        String sqlText = readStdin();
        ParseOutcome outcome = parseSql(sqlText);
        System.out.println(GSON.toJson(outcome.toJson()));
    }

    private static void processJsonl(Path inputPath, Path outputPath) throws IOException {
        try (BufferedReader reader = Files.newBufferedReader(inputPath, StandardCharsets.UTF_8);
                BufferedWriter writer = Files.newBufferedWriter(outputPath, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                JsonObject input = JsonParser.parseString(line).getAsJsonObject();
                String caseId = input.has("case_id") ? input.get("case_id").getAsString() : "";
                String sqlText = input.get("sql_text").getAsString();
                ParseOutcome outcome = parseSql(sqlText);
                JsonObject output = outcome.toJson();
                output.addProperty("case_id", caseId);
                writer.write(GSON.toJson(output));
                writer.newLine();
            }
        }
    }

    private static String readStdin() throws IOException {
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            boolean first = true;
            while ((line = reader.readLine()) != null) {
                if (!first) {
                    builder.append('\n');
                }
                builder.append(line);
                first = false;
            }
        }
        return builder.toString();
    }

    private static ParseOutcome parseSql(String sqlText) {
        try {
            ParseDriver driver = new ParseDriver();
            driver.parse(sqlText);
            return new ParseOutcome("pass", "", "", "", "parse_success", "", "");
        } catch (Throwable throwable) {
            String message = throwable.getMessage() == null ? throwable.toString() : throwable.getMessage();
            String rawErrorType = detectRawErrorType(message);
            String rawErrorSubtype = detectRawErrorSubtype(sqlText, message);
            return new ParseOutcome(
                    "fail",
                    alignErrorType(rawErrorType),
                    alignErrorSubtype(sqlText, message, rawErrorSubtype),
                    extractPosition(message),
                    message.replace('\n', ' ').replace('\r', ' ').trim(),
                    rawErrorType,
                    rawErrorSubtype);
        }
    }

    private static String detectRawErrorType(String message) {
        String normalizedMessage = message == null ? "" : message.toLowerCase();

        if (normalizedMessage.contains("mismatched input")) {
            return "mismatched_input";
        }
        if (normalizedMessage.contains("cannot recognize input")) {
            return "cannot_recognize_input";
        }
        if (normalizedMessage.contains("no viable alternative")) {
            return "no_viable_alternative";
        }
        if (normalizedMessage.contains("failed predicate")) {
            return "failed_predicate";
        }
        if (normalizedMessage.contains("missing eof") || normalizedMessage.contains("extraneous input")) {
            return "unexpected_eof";
        }
        if (normalizedMessage.contains("token recognition error")
                || normalizedMessage.contains("character")
                || normalizedMessage.contains("lexer")) {
            return "lexer_error";
        }
        return "parse_error";
    }

    private static String detectRawErrorSubtype(String sqlText, String message) {
        String normalizedSql = sqlText == null ? "" : sqlText.toLowerCase();
        String normalizedMessage = message == null ? "" : message.toLowerCase();

        if (normalizedMessage.contains("in table name")) {
            if (normalizedSql.startsWith("create table if ")) {
                return "reserved_keyword_if_clause";
            }
            return "reserved_keyword_table_name";
        }
        if (normalizedMessage.contains("if not exists clause")) {
            return "reserved_keyword_if_clause";
        }
        if (normalizedMessage.contains("create database statement")
                || normalizedMessage.contains("switch database statement")
                || normalizedMessage.contains("drop database statement")) {
            return "quoted_database_identifier_syntax";
        }
        if (normalizedMessage.contains("in create table statement") && normalizedSql.startsWith("create table")) {
            return "reserved_keyword_table_name";
        }
        if (normalizedMessage.contains("in function specification")) {
            return "invalid_function_modifier_syntax";
        }
        if (normalizedMessage.contains("in joinsource") && normalizedSql.contains("values")) {
            return "invalid_values_table_reference";
        }
        if (normalizedMessage.contains("column name in create table statement")) {
            return "invalid_column_name_character";
        }
        if (normalizedMessage.contains("scheduled query statement")) {
            return "invalid_scheduled_query_syntax";
        }
        if (normalizedSql.startsWith("alter table") && normalizedSql.contains("partition column")) {
            return "invalid_partition_column_syntax";
        }
        if (normalizedSql.startsWith("create role")) {
            return "invalid_role_identifier";
        }
        if (normalizedSql.contains("within group")) {
            return "within_group_syntax";
        }
        if (normalizedSql.contains("\"") && normalizedSql.contains("/")) {
            return "quoted_identifier_path_syntax";
        }
        if (normalizedSql.contains("`") && (normalizedSql.contains(".") || normalizedSql.contains(":"))) {
            return "backtick_identifier_character_constraint";
        }
        if (normalizedSql.contains(" over(") || normalizedSql.contains(" over (")) {
            return "window_clause_syntax";
        }
        if (normalizedSql.startsWith("with ")) {
            return "cte_syntax";
        }
        return "generic_parse_failure";
    }

    private static String alignErrorType(String rawErrorType) {
        if (rawErrorType == null || rawErrorType.isBlank()) {
            return "";
        }
        return "parse_error";
    }

    private static String alignErrorSubtype(String sqlText, String message, String rawErrorSubtype) {
        String normalizedSql = sqlText == null ? "" : sqlText.toLowerCase();
        if (normalizedSql.contains("\"") && normalizedSql.contains("/")) {
            return "quoted_identifier_path_syntax";
        }
        if (rawErrorSubtype != null && !rawErrorSubtype.isBlank() && !"generic_parse_failure".equals(rawErrorSubtype)) {
            return rawErrorSubtype;
        }
        return detectRawErrorSubtype(sqlText, message);
    }

    private static String extractPosition(String message) {
        if (message == null || message.isBlank()) {
            return "1:1";
        }

        Matcher lineColumnMatcher = LINE_COLUMN_PATTERN.matcher(message);
        if (lineColumnMatcher.find()) {
            return lineColumnMatcher.group(1) + ":" + lineColumnMatcher.group(2);
        }

        Matcher positionMatcher = POSITION_PATTERN.matcher(message);
        if (positionMatcher.find()) {
            return positionMatcher.group(1) + ":" + positionMatcher.group(2);
        }
        return "1:1";
    }

    private static final class ParseOutcome {
        private final String actualStatus;
        private final String actualErrorType;
        private final String actualErrorSubtype;
        private final String actualErrorPosition;
        private final String parserMessage;
        private final String rawErrorType;
        private final String rawErrorSubtype;

        private ParseOutcome(
                String actualStatus,
                String actualErrorType,
                String actualErrorSubtype,
                String actualErrorPosition,
                String parserMessage,
                String rawErrorType,
                String rawErrorSubtype) {
            this.actualStatus = actualStatus;
            this.actualErrorType = actualErrorType;
            this.actualErrorSubtype = actualErrorSubtype;
            this.actualErrorPosition = actualErrorPosition;
            this.parserMessage = parserMessage;
            this.rawErrorType = rawErrorType;
            this.rawErrorSubtype = rawErrorSubtype;
        }

        private JsonObject toJson() {
            JsonObject jsonObject = new JsonObject();
            jsonObject.addProperty("actual_status", actualStatus);
            jsonObject.addProperty("actual_error_type", actualErrorType);
            jsonObject.addProperty("actual_error_subtype", actualErrorSubtype);
            jsonObject.addProperty("actual_error_position", actualErrorPosition);
            jsonObject.addProperty("parser_message", parserMessage);
            jsonObject.addProperty("raw_error_type", rawErrorType);
            jsonObject.addProperty("raw_error_subtype", rawErrorSubtype);
            return jsonObject;
        }
    }
}
