import React, { useState } from "react";
import { View, Button, Image, Text, ScrollView, StyleSheet, Alert, Platform } from "react-native";
import * as ImagePicker from "expo-image-picker";

// ✅ BACKEND URL
// - On web: keep localhost (backend running on same machine).
// - On phone (Expo Go): REPLACE with your PC's IPv4 from `ipconfig`, e.g. "http://192.168.1.42:8000"
const BACKEND_URL =
  Platform.OS === "web" ? "http://127.0.0.1:8000" : "http://192.168.1.35:8000";

// ✅ UI color for results
const RESULT_COLOR = "#00C853"; // change to any color you like

type OcrLine = { text: string; confidence?: number };
type Structured = {
  ingredients?: { name: string; percent?: number | null }[];
  allergens?: string[];
  additives?: { code: string; name?: string | null }[];
  flags?: Record<string, boolean>;
};

// (optional) simple scoring stub you can tune later
function computeHealthScore(s: Structured | null): number | null {
  if (!s) return null;
  let score = 100;
  if (s.flags?.palmOil) score -= 10;
  if (s.flags?.addedSugar) score -= 15;
  if (s.flags?.addedSalt) score -= 10;
  if (s.flags?.msgLikeEnhancer) score -= 15;
  const additivePenalty = Math.min((s.additives?.length || 0) * 2, 20);
  score -= additivePenalty;
  return Math.max(0, score);
}

export default function HomeTab() {
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [lines, setLines] = useState<OcrLine[]>([]);
  const [structured, setStructured] = useState<Structured | null>(null);
  const [busy, setBusy] = useState(false);

  const uploadToBackend = async (form: FormData) => {
    const resp = await fetch(`${BACKEND_URL}/ocr`, { method: "POST", body: form });
    if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
    return resp.json();
  };

  const pickAndScan = async () => {
    setLines([]);
    setStructured(null);
    setBusy(true);
    try {
      let result: ImagePicker.ImagePickerResult;

      if (Platform.OS === "web") {
        // Web: open gallery (camera on web requires HTTPS in most browsers)
        result = await ImagePicker.launchImageLibraryAsync({ allowsEditing: false });
      } else {
        const { status } = await ImagePicker.requestCameraPermissionsAsync();
        if (status !== "granted") throw new Error("Camera permission denied");
        result = await ImagePicker.launchCameraAsync({ quality: 1 });
      }

      if (result.canceled) return;

      const asset = result.assets[0];
      setImageUri(asset.uri);

      // Build FormData differently for web vs native
      let form = new FormData();
      if (Platform.OS === "web") {
        const blob = await (await fetch(asset.uri)).blob(); // blob URL -> Blob
        form.append("file", blob, "photo.jpg"); // filename matters on web
      } else {
        form.append("file", {
          uri: asset.uri,
          name: "photo.jpg",
          type: "image/jpeg",
        } as any);
      }

      const json = await uploadToBackend(form);
      setLines(json?.lines || []);
      setStructured(json?.structured || null);
    } catch (e: any) {
      Alert.alert("OCR failed", e.message || "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  const score = computeHealthScore(structured);

  return (
    <View style={styles.container}>
      <Button title={busy ? "Scanning..." : "Scan Image"} onPress={pickAndScan} disabled={busy} />

      {imageUri && (
        <Image source={{ uri: imageUri }} style={styles.image} resizeMode="contain" />
      )}

      {/* Structured view */}
      {structured ? (
        <ScrollView style={{ marginTop: 12 }}>
          {score !== null && (
            <>
              <Text style={styles.section}>Health score</Text>
              <Text style={[styles.result, styles.big]}>{score}/100</Text>
            </>
          )}

          <Text style={styles.section}>Ingredients</Text>
          {structured.ingredients?.length ? (
            structured.ingredients.map((it, i) => (
              <Text key={i} style={styles.result}>
                {it.name}{it.percent != null ? ` (${it.percent}%)` : ""}
              </Text>
            ))
          ) : (
            <Text style={styles.muted}>No ingredients parsed.</Text>
          )}

          {structured.allergens?.length ? (
            <>
              <Text style={styles.section}>Allergens</Text>
              <Text style={styles.result}>{structured.allergens.join(", ")}</Text>
            </>
          ) : null}

          {structured.additives?.length ? (
            <>
              <Text style={styles.section}>Additives</Text>
              {structured.additives.map((a, i) => (
                <Text key={i} style={styles.result}>
                  {a.code}{a.name ? ` — ${a.name}` : ""}
                </Text>
              ))}
            </>
          ) : null}

          <Text style={styles.section}>Flags</Text>
          <Text style={styles.result}>
            {Object.entries(structured.flags || {})
              .filter(([, v]) => v)
              .map(([k]) => k)
              .join(", ") || "none"}
          </Text>
        </ScrollView>
      ) : (
        // Raw lines fallback (no probabilities shown)
        <ScrollView style={{ marginTop: 12 }}>
          {lines.length ? (
            lines.map((l, i) => (
              <Text key={i} style={styles.result}>{l.text}</Text>
            ))
          ) : (
            <Text style={styles.muted}>{busy ? "Recognizing..." : "No text yet. Tap Scan Image."}</Text>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, paddingTop: Platform.OS === "android" ? 32 : 16, backgroundColor: "#000" },
  image: { width: "100%", height: 240, marginTop: 12, backgroundColor: "#eee" },
  section: { marginTop: 12, fontWeight: "700", fontSize: 16, color: "#9E9E9E" },
  result: {
    color: RESULT_COLOR,
    fontSize: 18,
    fontWeight: "600",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: "#333",
  },
  big: { fontSize: 24 },
  muted: { opacity: 0.6, marginTop: 8, color: "#9E9E9E" },
});
