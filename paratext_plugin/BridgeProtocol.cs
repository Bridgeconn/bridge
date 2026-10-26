using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;

namespace TranslationCoreAiBridge.ParatextConnector
{
    public sealed class BridgeRequest
    {
        public int protocol { get; set; }
        public string id { get; set; }
        public string action { get; set; }
        public Dictionary<string, object> payload { get; set; }
    }

    public sealed class BridgeResponse
    {
        public BridgeResponse()
        {
            protocol = 1;
            capabilities = new string[0];
        }

        public int protocol { get; set; }
        public string id { get; set; }
        public bool ok { get; set; }
        public string error { get; set; }
        public string message { get; set; }

        public string user { get; set; }
        public string project_name { get; set; }
        public string project_id { get; set; }
        public string project_language { get; set; }
        public string reference { get; set; }
        public string selected_text { get; set; }
        public string selection_reference { get; set; }
        public string before_context { get; set; }
        public string after_context { get; set; }
        public int selection_offset { get; set; }
        public string sync_group { get; set; }
        public string paratext_version { get; set; }
        public string plugin_version { get; set; }
        public long state_revision { get; set; }
        public string last_event { get; set; }
        public string last_origin_id { get; set; }
        public bool note_created { get; set; }
        public string[] capabilities { get; set; }

        // 0.8.0 (#358): every Paratext project this PC holds, so Bridge can
        // address a note by project id rather than by whatever window is active.
        public List<Dictionary<string, object>> projects { get; set; }
        // 0.8.0: what create_note / add_comment answer with. A Paratext note has
        // no id; (author, created) is the only identity its file carries, so
        // Bridge keeps both to find the thread again.
        public string author { get; set; }
        public string created { get; set; }
        public Dictionary<string, object> anchor { get; set; }
        public bool comment_added { get; set; }
        public bool resolved { get; set; }
        // 0.8.0: list_notes.
        public List<Dictionary<string, object>> notes { get; set; }
    }

    internal static class BridgeJson
    {
        internal static readonly JavaScriptSerializer Serializer = new JavaScriptSerializer();

        internal static string GetString(IDictionary<string, object> payload, string key)
        {
            if (payload == null || !payload.ContainsKey(key) || payload[key] == null)
                return String.Empty;
            return Convert.ToString(payload[key]) ?? String.Empty;
        }

        internal static bool GetBool(IDictionary<string, object> payload, string key)
        {
            if (payload == null || !payload.ContainsKey(key) || payload[key] == null)
                return false;
            object value = payload[key];
            if (value is bool) return (bool)value;
            string text = Convert.ToString(value) ?? String.Empty;
            return text.Equals("true", StringComparison.OrdinalIgnoreCase) || text == "1";
        }

        internal static int GetInt(IDictionary<string, object> payload, string key, int fallback)
        {
            if (payload == null || !payload.ContainsKey(key) || payload[key] == null)
                return fallback;
            int parsed;
            if (Int32.TryParse(Convert.ToString(payload[key]), out parsed)) return parsed;
            return fallback;
        }

        internal static IDictionary<string, object> GetObject(IDictionary<string, object> payload, string key)
        {
            if (payload == null || !payload.ContainsKey(key)) return null;
            return payload[key] as IDictionary<string, object>;
        }
    }
}
