package com.omnicfo.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class WhatsAppProcessingService {
    private static final long PROCESS_TIMEOUT_MINUTES = 15;

    private final ObjectMapper objectMapper;

    public List<Map<String, Object>> process(MultipartFile upload) {
        Path workDir = null;
        try {
            workDir = Files.createTempDirectory("whatsapp-processing-");
            String fileName = safeFileName(upload.getOriginalFilename());
            Path zipPath = workDir.resolve(fileName);
            try (var input = upload.getInputStream()) {
                Files.copy(input, zipPath, StandardCopyOption.REPLACE_EXISTING);
            }

            Path moduleDir = resolveModuleDirectory();
            Path parserPath = moduleDir.resolve("parser.py");
            Path extractorPath = moduleDir.resolve("extractor_gemini.py");
            if (!Files.isRegularFile(parserPath) || !Files.isRegularFile(extractorPath)) {
                throw new IllegalStateException(
                    "WhatsApp module not found. Set WHATSAPP_MODULE_PATH to the directory containing parser.py "
                        + "and extractor_gemini.py."
                );
            }

            runPython(List.of(parserPath.toString(), zipPath.toString()), workDir);
            Path parsedPath = workDir.resolve(withoutExtension(fileName) + "_parsed.json");
            runPython(List.of(extractorPath.toString(), parsedPath.toString()), workDir);

            Path insightsPath = workDir.resolve("insights.json");
            if (!Files.isRegularFile(insightsPath)) {
                throw new IllegalStateException("WhatsApp extractor did not produce insights.json");
            }
            JsonNode root = objectMapper.readTree(insightsPath.toFile());
            JsonNode itemsNode = root.path("items");
            if (!itemsNode.isArray()) {
                throw new IllegalStateException("WhatsApp extractor response does not contain an items array");
            }
            return objectMapper.convertValue(itemsNode, new TypeReference<List<Map<String, Object>>>() {});
        } catch (IOException e) {
            throw new IllegalStateException("Failed to run WhatsApp processing", e);
        } finally {
            deleteWorkDirectory(workDir);
        }
    }

    private void runPython(List<String> scriptArguments, Path workDir) throws IOException {
        String pythonCommand = System.getenv().getOrDefault("WHATSAPP_PYTHON_COMMAND", "python");
        List<String> command = new ArrayList<>();
        command.add(pythonCommand);
        command.addAll(scriptArguments);

        Process process = new ProcessBuilder(command)
            .directory(workDir.toFile())
            .redirectErrorStream(true)
            .start();
        String output;
        try (var outputStream = process.getInputStream()) {
            output = new String(outputStream.readAllBytes(), StandardCharsets.UTF_8);
        }
        try {
            if (!process.waitFor(PROCESS_TIMEOUT_MINUTES, TimeUnit.MINUTES)) {
                process.destroyForcibly();
                throw new IllegalStateException("WhatsApp Python processing timed out");
            }
        } catch (InterruptedException e) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw new IllegalStateException("WhatsApp Python processing was interrupted", e);
        }
        if (process.exitValue() != 0) {
            throw new IllegalStateException("WhatsApp Python processing failed: " + output.trim());
        }
        log.info("WhatsApp Python step completed: {}", output.trim());
    }

    private Path resolveModuleDirectory() {
        String configured = System.getenv().getOrDefault("WHATSAPP_MODULE_PATH", "whatsapp-module");
        List<Path> candidates = List.of(
            Path.of(configured),
            Path.of("whatsapp-module"),
            Path.of("..", "whatsapp-module")
        );
        return candidates.stream()
            .map(Path::toAbsolutePath)
            .map(Path::normalize)
            .filter(Files::isDirectory)
            .findFirst()
            .orElse(Path.of(configured).toAbsolutePath().normalize());
    }

    private static String safeFileName(String originalName) {
        String name = originalName == null || originalName.isBlank() ? "whatsapp-export.zip" : originalName;
        name = Path.of(name).getFileName().toString();
        if (!name.toLowerCase().endsWith(".zip")) {
            throw new IllegalArgumentException("WhatsApp upload must be a .zip file");
        }
        return name;
    }

    private static String withoutExtension(String fileName) {
        int extensionIndex = fileName.lastIndexOf('.');
        return extensionIndex > 0 ? fileName.substring(0, extensionIndex) : fileName;
    }

    private static void deleteWorkDirectory(Path workDir) {
        if (workDir == null) {
            return;
        }
        try (var paths = Files.walk(workDir)) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                try {
                    Files.deleteIfExists(path);
                } catch (IOException e) {
                    log.warn("Could not delete temporary WhatsApp file {}", path, e);
                }
            });
        } catch (IOException e) {
            log.warn("Could not clean temporary WhatsApp directory {}", workDir, e);
        }
    }
}
