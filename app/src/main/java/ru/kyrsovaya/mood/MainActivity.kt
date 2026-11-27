package ru.kyrsovaya.mood

import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val debug = applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        val address = if (debug) "http://10.0.2.2:8080/" else getString(R.string.server_url)
        val allowed = Uri.parse(address)
        if (allowed.host.isNullOrBlank() || (!debug && allowed.scheme != "https")) {
            setContentView(TextView(this).apply { text = "Укажите HTTPS-адрес сервера." })
            return
        }
        webView = WebView(this)
        webView.settings.apply {
            javaScriptEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(webView, false)
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val next = request.url
                return next.scheme != allowed.scheme || next.host != allowed.host || next.port != allowed.port
            }

            override fun onPageFinished(view: WebView, url: String) {
                CookieManager.getInstance().flush()
            }
        }
        setContentView(webView)
        webView.loadUrl(address)
    }

    override fun onPause() {
        CookieManager.getInstance().flush()
        super.onPause()
    }
}
